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
import pickle
import re
from collections.abc import Iterator
from multiprocessing.pool import Pool
from pathlib import Path

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from logzero import logger
from tqdm import tqdm

from common import PAGE_TYPE_ARTICLE, normalize_title


# https://meta.wikimedia.org/wiki/List_of_Wikipedias#Redirects
# https://meta.wikimedia.org/w/api.php?action=query&meta=siteinfo&siprop=interwikimap&formatversion=2
LANG_REDIRECTS = {
    "be-x-old": "be-tarask",
    "cz": "cs",
    "dk": "da",
    "jp": "ja",
    "mo": "ro",
    "nan": "zh-min-nan",
    "nb": "no",
    "yue": "zh-yue",
}


def extract_article_redirects(page_dataset_files: list[str]) -> dict[tuple[str, str], str]:
    article_redirects = {}  # (lang, source title) -> target title

    for page_dataset_file in page_dataset_files:
        with gzip.open(page_dataset_file, "rt") as f:
            for line in tqdm(f):
                example = json.loads(line)

                if example["page_type"] != PAGE_TYPE_ARTICLE:
                    continue

                lang = example["lang"]
                title = example["title"]
                source_titles = example["redirects"]

                for source_title in source_titles:
                    if (lang, source_title) in article_redirects:
                        # It is possible that multiple aricles have tha same title due to the creation timing of
                        # Wikipedia Cirrussearch dump files
                        assert article_redirects[(lang, source_title)] == title
                    else:
                        article_redirects[(lang, source_title)] = title

    return article_redirects


def extract_texts_and_links_from_tag(
    tag: Tag,
    lang: str,
    title: str,
    add_pseudo_self_wikilinks: bool = False,
    extracted_texts_and_links: list[tuple[str, str | None]] | None = None,
    noprint: bool = False,
    is_mobile_html: bool = False,
) -> list[tuple[str, tuple[str, str] | None]]:
    if extracted_texts_and_links is None:
        extracted_texts_and_links = []

    for child in tag.children:
        text = child.get_text()

        if isinstance(child, NavigableString) and not isinstance(child, Comment):
            if text != "" and not noprint:
                extracted_texts_and_links.append((text, None))
        elif isinstance(child, Tag):
            if child.name == ("span" if is_mobile_html else "a") and "new" in child.get("class", []):
                if text != "" and not noprint:
                    extracted_texts_and_links.append((text, ""))
            elif child.name == "a" and child.has_attr("href") and child.has_attr("title"):
                if "extiw" in child.get("class", []):
                    link = child["title"]  # f"{link_lang}:{link_title}"
                    if len(extracted_texts_and_links) > 0:
                        last_text, last_link = extracted_texts_and_links[-1]
                        if last_link == "":
                            extracted_texts_and_links[-1] = (last_text, link)
                elif re.match(r"\./(.+)", child["href"]):
                    link = f"{lang}:{child['title']}"
                else:
                    link = None

                if text != "" and not noprint:
                    extracted_texts_and_links.append((text, link))
            elif child.name == "b" and add_pseudo_self_wikilinks:
                if text != "" and not noprint:
                    extracted_texts_and_links.append((text, f"{lang}:{title}"))
                    add_pseudo_self_wikilinks = False
            else:
                child_noprint = noprint or "noprint" in child.get("class", [])
                extracted_texts_and_links = extract_texts_and_links_from_tag(
                    child,
                    lang,
                    title,
                    add_pseudo_self_wikilinks=add_pseudo_self_wikilinks,
                    extracted_texts_and_links=extracted_texts_and_links,
                    noprint=child_noprint,
                    is_mobile_html=is_mobile_html,
                )

    extracted_texts_and_links = [(text, link or None) for text, link in extracted_texts_and_links]

    return extracted_texts_and_links


def generate_paragraphs_from_html(
    html: str,
    lang: str,
    title: str,
    paragraph_tags: list[str],
    article_redirects: dict[tuple[str, str], str],
    is_mobile_html: bool = False,
    add_pseudo_self_wikilinks: bool = False,
) -> Iterator[tuple[str, str, list[dict[str, int | str | None]], str]]:
    section_title = "__LEAD__"
    is_first_paragraph_processed = False

    soup = BeautifulSoup(html, features="lxml")
    body_tag = soup.html.body

    for section_tag in body_tag.find_all("section"):
        for table_tag in section_tag.find_all("table"):
            table_tag.decompose()

        for div_tag in section_tag.find_all("div", recursive=False):
            if "columns-list__wrapper" in div_tag.get("class", []):
                continue

            div_tag.decompose()

        for math_tag in section_tag.find_all("math"):
            math_tag.decompose()

        for ref_tag in section_tag.find_all(class_="mw-ref"):
            ref_tag.decompose()

        for cite_backlink_tag in section_tag.find_all(class_="mw-cite-backlink"):
            cite_backlink_tag.decompose()

        # https://github.com/wikimedia/mediawiki-services-mobileapps/blob/13331c8da18f97a410d0f114ae8e452bde95b045/lib/mobile/MobileHTML.js#L406
        if any(
            not references_tag.has_attr("data-mw-group")
            for references_tag in section_tag.find_all("ol", class_="mw-references")
        ):
            break

        if section_tag.h2 is not None:
            section_title = section_tag.h2.text.strip()

        for paragraph_tag in section_tag.find_all(paragraph_tags):
            paragraph_text = ""
            wikilinks = []

            for text, link in extract_texts_and_links_from_tag(
                paragraph_tag,
                lang,
                title,
                add_pseudo_self_wikilinks=add_pseudo_self_wikilinks and not is_first_paragraph_processed,
                is_mobile_html=is_mobile_html,
            ):
                if link is not None:
                    link_lang, link_title = link.split(":", maxsplit=1)
                    link_lang = LANG_REDIRECTS.get(link_lang, link_lang)
                    link_title = normalize_title(link_title)

                    if (link_lang, link_title) in article_redirects:
                        link_title = article_redirects[(link_lang, link_title)]
                        link_text = text.strip()
                        if link_text != "":
                            link_lspace_length = len(text) - len(text.lstrip())
                            link_start = len(paragraph_text) + link_lspace_length
                            link_end = link_start + len(link_text)

                            wikilink = {
                                "lang": link_lang,
                                "title": link_title,
                                "text": link_text,
                                "start": link_start,
                                "end": link_end,
                            }
                            wikilinks.append(wikilink)

                paragraph_text += text

            paragraph_lspace_length = len(paragraph_text) - len(paragraph_text.lstrip())
            if paragraph_lspace_length > 0:
                for wikilink in wikilinks:
                    wikilink["start"] -= paragraph_lspace_length
                    wikilink["end"] -= paragraph_lspace_length

            paragraph_text = paragraph_text.strip()
            if paragraph_text != "":
                yield paragraph_text, section_title, wikilinks, paragraph_tag.name
                is_first_paragraph_processed = True

            paragraph_tag.decompose()

        section_tag.decompose()


def _create_paragraph_dataset(
    page_html_dataset_files: list[str],
    output_dir: str,
    article_redirects: dict[tuple[str, str], str],
    paragraph_tags: list[str],
    add_pseudo_self_wikilinks: bool = False,
    num_processes: int | None = None,
    process_idx: int | None = None,
) -> int:
    num_examples = 0

    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)
    if num_processes is not None:
        output_file_path = output_dir_path / f"shard-{process_idx:03d}-of-{num_processes:03d}.jsonl.gz"
    else:
        output_file_path = output_dir_path / "shard-000-of-001.jsonl.gz"

    with gzip.open(output_file_path, "wt") as fo:
        for page_html_dataset_file in page_html_dataset_files:
            with gzip.open(page_html_dataset_file, "rt") as f:
                for idx, line in tqdm(enumerate(f), disable=process_idx):
                    if num_processes is not None and idx % num_processes != process_idx:
                        continue

                    example = json.loads(line)

                    id_ = example["id"]
                    lang = example["lang"]
                    page_id = example["page_id"]
                    revision_id = example["revision_id"]
                    page_type = example["page_type"]
                    title = example["title"]
                    html = example["html"]
                    html_source = example["html_source"]

                    paragraph_texts = []
                    paragraph_sections = []
                    paragraph_wikilinks = []
                    paragraph_html_tags = []

                    for text, section, wikilinks, html_tag in generate_paragraphs_from_html(
                        html,
                        lang,
                        title,
                        paragraph_tags,
                        article_redirects,
                        is_mobile_html="mobile" in html_source,
                        add_pseudo_self_wikilinks=add_pseudo_self_wikilinks,
                    ):
                        paragraph_texts.append(text)
                        paragraph_sections.append(section)
                        paragraph_wikilinks.append(wikilinks)
                        paragraph_html_tags.append(html_tag)

                    output_example = {
                        "id": id_,
                        "lang": lang,
                        "page_id": page_id,
                        "revision_id": revision_id,
                        "page_type": page_type,
                        "title": title,
                        "paragraph_texts": paragraph_texts,
                        "paragraph_sections": paragraph_sections,
                        "paragraph_wikilinks": paragraph_wikilinks,
                        "paragraph_html_tags": paragraph_html_tags,
                    }
                    print(json.dumps(output_example, ensure_ascii=False), file=fo)
                    num_examples += 1

    return num_examples


def create_paragraph_dataset(
    page_html_dataset_files: list[str],
    output_dir: str,
    article_redirects: dict[tuple[str, str], str],
    paragraph_tags: list[str],
    add_pseudo_self_wikilinks: bool = False,
    num_processes: int | None = None,
) -> int:
    if num_processes is not None:
        args = [
            (
                page_html_dataset_files,
                output_dir,
                article_redirects,
                paragraph_tags,
                add_pseudo_self_wikilinks,
                num_processes,
                process_idx,
            )
            for process_idx in range(num_processes)
        ]
        with Pool(num_processes) as pool:
            num_examples = sum(pool.starmap(_create_paragraph_dataset, args))
    else:
        num_examples = _create_paragraph_dataset(
            page_html_dataset_files,
            output_dir,
            article_redirects,
            paragraph_tags,
            add_pseudo_self_wikilinks=add_pseudo_self_wikilinks,
        )

    return num_examples


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--page_dataset_files", nargs="+", type=str, required=True)
    parser.add_argument("--page_html_dataset_files", nargs="+", type=str, required=True)
    parser.add_argument("--output_dir", type=str, required=True)
    parser.add_argument("--paragraph_tags", nargs="+", type=str, required=True)
    parser.add_argument("--add_pseudo_self_wikilinks", action="store_true")
    parser.add_argument("--article_redirects_file", type=str)
    parser.add_argument("--num_processes", type=int)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logger.setLevel("DEBUG" if args.debug else "INFO")

    if Path(args.output_dir).exists():
        raise FileExistsError(args.output_dir)

    if args.article_redirects_file is not None and Path(args.article_redirects_file).exists():
        logger.info("Loading saved article redirects")
        with open(args.article_redirects_file, "rb") as f:
            article_redirects = pickle.load(f)
    else:
        logger.info("Extracting article redirects from page datasets")
        article_redirects = extract_article_redirects(args.page_dataset_files)

    if args.article_redirects_file is not None and not Path(args.article_redirects_file).exists():
        logger.info("Saving article redirects")
        with open(args.article_redirects_file, "wb") as fo:
            pickle.dump(article_redirects, fo)

    logger.info("Creating a paragraph dataset from the page HTML dataset")
    num_examples = create_paragraph_dataset(
        args.page_html_dataset_files,
        args.output_dir,
        article_redirects,
        args.paragraph_tags,
        add_pseudo_self_wikilinks=args.add_pseudo_self_wikilinks,
        num_processes=args.num_processes,
    )
    logger.info("Finished creating dataset of %d examples", num_examples)


if __name__ == "__main__":
    main()
