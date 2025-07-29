# Copyright 2025 Masatoshi Suzuki (@singletongue)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import argparse
import gzip
import json
from collections import Counter, defaultdict
from collections.abc import Iterator
from multiprocessing import Pool
from pathlib import Path
from typing import Any

import mwparserfromhell
import requests
from logzero import logger
from tqdm import tqdm

from common import (
    NAMESPACE_ARTICLE,
    NAMESPACE_CATEGORY,
    NAMESPACE_TEMPLATE,
    get_page_type_from_namespace,
    normalize_title,
)


def fetch_category_prefixes(lang: str) -> list[str]:
    url = f"https://{lang}.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "meta": "siteinfo",
        "siprop": "namespaces|namespacealiases",
        "formatversion": 2,
        "format": "json",
    }
    response = requests.get(url, params)
    response.raise_for_status()
    response_data = response.json()

    category_prefixes = []

    for namespace_item in response_data["query"]["namespaces"].values():
        if namespace_item["id"] == NAMESPACE_CATEGORY:
            if namespace_item["canonical"] not in category_prefixes:
                category_prefixes.append(namespace_item["canonical"])

            if namespace_item["name"] not in category_prefixes:
                category_prefixes.append(namespace_item["name"])

    for alias_item in response_data["query"]["namespacealiases"]:
        if alias_item["id"] == NAMESPACE_CATEGORY:
            if alias_item["alias"] not in category_prefixes:
                category_prefixes.append(alias_item["alias"])

    category_prefixes = [f"{prefix}:" for prefix in category_prefixes]

    return category_prefixes


def generate_items_from_cirrussearch_files(cirrussearch_files: list[str], lang: str) -> Iterator[dict[str, Any]]:
    for cirrussearch_file in cirrussearch_files:
        with gzip.open(cirrussearch_file, "rt") as f:
            for line in f:
                item = json.loads(line)

                if "index" in item:
                    continue
                if item["namespace"] not in (NAMESPACE_ARTICLE, NAMESPACE_CATEGORY, NAMESPACE_TEMPLATE):
                    continue
                if item["language"] != lang:
                    # Most pages in the Norwegian Wikipedia (nowiki) has the "nb" lang code.
                    if lang == "no" and item["language"] == "nb":
                        pass
                    else:
                        continue

                yield item


def extract_redirect_candidates(cirrussearch_files: list[str], lang: str) -> dict[tuple[int, str], list[str]]:
    redirect_candidates = defaultdict(list)  # (namespace, source title) -> target titles

    for item in tqdm(generate_items_from_cirrussearch_files(cirrussearch_files, lang)):
        namespace = item["namespace"]

        target_title = normalize_title(item["title"])
        if (namespace, target_title) not in redirect_candidates:
            redirect_candidates[(namespace, target_title)].append(target_title)

        for redirect_item in item["redirect"]:
            if redirect_item["namespace"] != namespace:
                continue

            source_title = normalize_title(redirect_item["title"])
            if (namespace, source_title) not in redirect_candidates:
                redirect_candidates[(namespace, source_title)].append(target_title)

    return dict(redirect_candidates)


def normalize_redirects(redirect_candidates: dict[tuple[int, str], list[str]]) -> dict[tuple[int, str], str]:
    redirects = {}  # (namespace, source title) -> target title

    for (namespace, source_title), target_titles in redirect_candidates.items():
        if len(target_titles) > 1:
            if source_title in target_titles:
                logger.debug(
                    "Normalizing duplicated redirect (ns=%d): (%s -> %s) => (%s -> %s)",
                    namespace,
                    source_title,
                    target_titles,
                    source_title,
                    source_title,
                )
                redirects[(namespace, source_title)] = source_title
            else:
                logger.debug(
                    "Dropping duplicated redirect (ns=%d): (%s -> %s) => null", namespace, source_title, target_titles
                )

        elif len(target_titles) == 1:
            redirects[(namespace, source_title)] = target_titles[0]

    return redirects


def _extract_linked_pages(
    cirrussearch_files: list[str],
    lang: str,
    category_prefixes: list[str],
    redirects: dict[tuple[int, str], str],
    num_processes: int | None = None,
    process_idx: int | None = None,
) -> dict[int, list[tuple[int, str]]]:
    linked_pages = {}  # page id -> list of (namespace, title)

    for idx, item in tqdm(
        enumerate(generate_items_from_cirrussearch_files(cirrussearch_files, lang)), disable=process_idx
    ):
        if num_processes is not None and idx % num_processes != process_idx:
            continue

        page_id = item["page_id"]
        wikicode = mwparserfromhell.parse(item["source_text"])

        page_linked_pages = []

        for wikilink_node in wikicode.ifilter_wikilinks():
            wikilink_title = str(wikilink_node.title)

            for category_prefix in category_prefixes:
                if wikilink_title[: len(category_prefix)].lower() == category_prefix.lower():
                    category = normalize_title(wikilink_title[len(category_prefix) :])
                    category = redirects.get((NAMESPACE_CATEGORY, category))
                    if category is not None:
                        if (NAMESPACE_CATEGORY, category) not in page_linked_pages:
                            page_linked_pages.append((NAMESPACE_CATEGORY, category))

                    break
            else:
                article = normalize_title(wikilink_title)
                article = redirects.get((NAMESPACE_ARTICLE, article))
                if article is not None:
                    if (NAMESPACE_ARTICLE, article) not in page_linked_pages:
                        page_linked_pages.append((NAMESPACE_ARTICLE, article))

        for template_node in wikicode.ifilter_templates():
            # Remove the substitution marker from the template name
            # cf. https://en.wikipedia.org/wiki/Help:Template
            template = normalize_title(str(template_node.name).removeprefix("subst:"))
            template = redirects.get((NAMESPACE_TEMPLATE, template))
            if template is not None:
                if (NAMESPACE_TEMPLATE, template) not in page_linked_pages:
                    page_linked_pages.append((NAMESPACE_TEMPLATE, template))

        assert page_id not in linked_pages
        linked_pages[page_id] = page_linked_pages

    return linked_pages


def extract_linked_pages(
    cirrussearch_files: list[str],
    lang: str,
    category_prefixes: list[str],
    redirects: dict[tuple[int, str], str],
    num_processes: int | None = None,
) -> dict[int, list[tuple[int, str]]]:
    if num_processes is not None:
        linked_pages = {}  # page id -> list of (namespace, title)

        args = [
            (cirrussearch_files, lang, category_prefixes, redirects, num_processes, process_idx)
            for process_idx in range(num_processes)
        ]
        with Pool(num_processes) as pool:
            for _linked_pages in pool.starmap(_extract_linked_pages, args):
                assert len(set(linked_pages) & set(_linked_pages)) == 0
                linked_pages.update(_linked_pages)

    else:
        linked_pages = _extract_linked_pages(cirrussearch_files, lang, category_prefixes, redirects)

    return linked_pages


def get_num_inlinks(linked_pages: dict[int, list[tuple[int, str]]]) -> dict[tuple[int, str], int]:
    num_inlinks = Counter(
        (namespace, link_title)
        for page_linked_pages in linked_pages.values()
        for (namespace, link_title) in page_linked_pages
    )
    return dict(num_inlinks)


def get_inverse_redirects(redirects: dict[tuple[int, str], str]) -> dict[tuple[int, str], list[str]]:
    inverse_redirects = defaultdict(list)  # (namespace, target title) -> source titles
    for (namespace, source_title), target_title in redirects.items():
        inverse_redirects[(namespace, target_title)].append(source_title)

    return dict(inverse_redirects)


def create_page_dataset(
    cirrussearch_files: list[str],
    output_file: str,
    lang: str,
    linked_pages: dict[int, list[tuple[int, str]]],
    num_inlinks: dict[tuple[int, str], int],
    inverse_redirects: dict[tuple[int, str], list[str]],
) -> int:
    num_examples = 0

    Path(output_file).parent.mkdir(parents=True, exist_ok=True)

    with gzip.open(output_file, "wt") as fo:
        for item in tqdm(generate_items_from_cirrussearch_files(cirrussearch_files, lang)):
            page_id = item["page_id"]
            revision_id = item["version"]
            id_ = f"{lang}-{page_id}-{revision_id}"

            namespace = item["namespace"]
            page_type = get_page_type_from_namespace(namespace)
            title = normalize_title(item["title"])

            wikidata_qid = item.get("wikibase_item")
            wikitext = item["source_text"]

            page_linked_articles = []
            page_linked_categories = []
            page_linked_templates = []

            for link_namespace, link_title in linked_pages[page_id]:
                if link_namespace == NAMESPACE_ARTICLE:
                    page_linked_articles.append(link_title)
                elif link_namespace == NAMESPACE_CATEGORY:
                    page_linked_categories.append(link_title)
                elif link_namespace == NAMESPACE_TEMPLATE:
                    page_linked_templates.append(link_title)

            page_num_inlinks = num_inlinks.get((namespace, title), 0)
            page_redirects = inverse_redirects.get((namespace, title), [])

            output_example = {
                "id": id_,
                "lang": lang,
                "page_id": page_id,
                "revision_id": revision_id,
                "page_type": page_type,
                "title": title,
                "wikidata_qid": wikidata_qid,
                "wikitext": wikitext,
                "linked_articles": page_linked_articles,
                "categories": page_linked_categories,
                "templates": page_linked_templates,
                "num_inlinks": page_num_inlinks,
                "redirects": page_redirects,
            }
            print(json.dumps(output_example, ensure_ascii=False), file=fo)
            num_examples += 1

    return num_examples


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cirrussearch_files", nargs="+", type=str, required=True)
    parser.add_argument("--output_file", type=str, required=True)
    parser.add_argument("--lang", type=str, required=True)
    parser.add_argument("--num_processes", type=int)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logger.setLevel("DEBUG" if args.debug else "INFO")

    if Path(args.output_file).exists():
        raise FileExistsError(args.output_file)

    logger.info("Fetching category prefixes for lang %s", args.lang)
    category_prefixes = fetch_category_prefixes(args.lang)
    logger.debug("Category prefixes: %s", category_prefixes)

    logger.info("Extracting redirects from Cirrussearch dump files")
    redirect_candidates = extract_redirect_candidates(args.cirrussearch_files, args.lang)

    logger.info("Normalizing redirects")
    redirects = normalize_redirects(redirect_candidates)
    del redirect_candidates

    logger.info("Extracting page link information from Cirrussearch dump files")
    linked_pages = extract_linked_pages(
        args.cirrussearch_files, args.lang, category_prefixes, redirects, num_processes=args.num_processes
    )

    logger.info("Counting number of inlinks for each page")
    num_inlinks = get_num_inlinks(linked_pages)

    logger.info("Generating inverse redirects")
    inverse_redirects = get_inverse_redirects(redirects)
    del redirects

    logger.info("Creating page dataset")
    num_examples = create_page_dataset(
        args.cirrussearch_files, args.output_file, args.lang, linked_pages, num_inlinks, inverse_redirects
    )
    logger.info("Finished creating page dataset of %d examples", num_examples)


if __name__ == "__main__":
    main()
