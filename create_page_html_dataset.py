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
import tarfile
from collections.abc import Iterator
from pathlib import Path
from time import sleep
from typing import Any
from urllib.parse import quote

import grequests
from loguru import logger
from tqdm import tqdm

from common import PAGE_TYPE_CATEGORY, PAGE_TYPE_TEMPLATE


def load_page_info_from_page_dataset(
    page_dataset_file: str, page_dataset_ids: list[str] | None = None
) -> dict[tuple[str, int, int], tuple[str, str]]:
    if page_dataset_ids is not None:
        page_dataset_ids = set(page_dataset_ids)

    page_info = {}  # (lang, page id, revision id) -> (page type, title)

    with gzip.open(page_dataset_file, "rt") as f:
        for line in tqdm(f):
            example = json.loads(line)

            if page_dataset_ids is not None and example["id"] not in page_dataset_ids:
                continue

            lang = example["lang"]
            page_id = example["page_id"]
            revision_id = example["revision_id"]

            page_type = example["page_type"]
            title = example["title"]

            assert (lang, page_id, revision_id) not in page_info
            page_info[(lang, page_id, revision_id)] = (page_type, title)

    return page_info


def load_wikitexts_from_page_dataset(
    page_dataset_file: str, page_info: dict[tuple[str, int, int], tuple[str, str]]
) -> dict[tuple[str, int, int], str]:
    wikitexts = {}  # (lang, page id, revision id) -> wikitext

    with gzip.open(page_dataset_file, "rt") as f:
        for line in tqdm(f):
            example = json.loads(line)

            lang = example["lang"]
            page_id = example["page_id"]
            revision_id = example["revision_id"]

            if (lang, page_id, revision_id) not in page_info:
                continue

            wikitext = example["wikitext"]

            assert (lang, page_id, revision_id) not in wikitexts
            wikitexts[(lang, page_id, revision_id)] = wikitext

    return wikitexts


def generate_items_from_enterprise_html_files(enterprise_html_files: list[str]) -> Iterator[dict[str, Any]]:
    for enterprise_html_file in enterprise_html_files:
        with tarfile.open(enterprise_html_file, "r:gz") as tar:
            for tarinfo in tar:
                with tar.extractfile(tarinfo) as f:
                    for line in f:
                        item = json.loads(line)
                        yield item


def create_page_html_dataset_from_enterprise_html_files(
    enterprise_html_files: list[str], page_info: dict[tuple[str, int, int], tuple[str, str]], output_file: str
) -> tuple[int, dict[tuple[str, int, int], tuple[str, str]]]:
    num_examples = 0
    remaining_page_info = page_info.copy()  # (lang, page_id, revision_id) -> (page_type, title)

    Path(output_file).parent.mkdir(parents=True, exist_ok=True)

    with gzip.open(output_file, "at") as fo:
        for item in tqdm(generate_items_from_enterprise_html_files(enterprise_html_files)):
            try:
                lang = item["in_language"]["identifier"]
                page_id = item["identifier"]
                revision_id = item["version"]["identifier"]
                html = (item["article_body"].get("html") or "").strip()
            except KeyError:
                continue

            # Most pages in the Norwegian Wikipedia (nowiki) has the "nb" lang code.
            if lang == "nb":
                lang = "no"

            if (lang, page_id, revision_id) not in page_info:
                continue

            id_ = f"{lang}-{page_id}-{revision_id}"
            page_type, title = page_info[(lang, page_id, revision_id)]

            if (lang, page_id, revision_id) not in remaining_page_info:
                logger.debug(
                    "Duplicated item: lang={}, page_id={}, revision_id={}, title={}", lang, page_id, revision_id, title
                )
                continue

            if html == "":
                logger.debug(
                    "HTML is empty: lang={}, page_id={}, revision_id={}, title={}", lang, page_id, revision_id, title
                )
                continue

            output_example = {
                "id": id_,
                "lang": lang,
                "page_id": page_id,
                "revision_id": revision_id,
                "page_type": page_type,
                "title": title,
                "html": html,
                "html_source": "enterprise_html",
            }
            print(json.dumps(output_example, ensure_ascii=False), file=fo)
            num_examples += 1
            remaining_page_info.pop((lang, page_id, revision_id))

    return num_examples, remaining_page_info


def create_page_html_dataset_with_get_page_html_api(
    page_info: dict[tuple[str, int, int], tuple[str, str]],
    output_file: str,
    user_agent: str,
    get_mobile_html: bool = False,
    get_latest_revision: bool = False,
    request_batch_size: int = 1,
    timeout: int = 60,
) -> tuple[int, dict[tuple[str, int, int], tuple[str, str]]]:
    if get_latest_revision:
        logger.warning(
            "When get_latest_revision option is set, the revision IDs of the page HTMLs fetched may not be the same as"
            "those in the page dataset."
        )

    headers = {"User-Agent": user_agent}
    if get_mobile_html:
        html_source = "get_mobile_html"
    else:
        html_source = "get_html"

    num_examples = 0
    remaining_page_info = page_info.copy()  # (lang, page_id, revision_id) -> (page_type, title)

    Path(output_file).parent.mkdir(parents=True, exist_ok=True)

    with gzip.open(output_file, "at") as fo, tqdm(total=len(page_info)) as pbar:
        batch_page_info = []
        batch_requests = []

        for idx, (lang, page_id, revision_id) in enumerate(page_info):
            page_type, title = page_info[(lang, page_id, revision_id)]

            query_title = quote(title.replace(" ", "_"), safe="")
            if page_type == PAGE_TYPE_CATEGORY:
                query_title = "Category:" + query_title
            elif page_type == PAGE_TYPE_TEMPLATE:
                query_title = "Template:" + query_title

            if get_mobile_html:
                if get_latest_revision:
                    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/mobile-html/{query_title}"
                else:
                    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/mobile-html/{query_title}/{revision_id}"
            else:
                if get_latest_revision:
                    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/html/{query_title}"
                else:
                    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/html/{query_title}/{revision_id}"

            batch_page_info.append((lang, page_id, revision_id))
            batch_requests.append(grequests.get(url, headers=headers, timeout=timeout))

            if len(batch_page_info) >= request_batch_size or idx == len(page_info) - 1:
                batch_responses = grequests.map(batch_requests)
                assert len(batch_page_info) == len(batch_requests) == len(batch_responses)

                for (lang, page_id, revision_id), response in zip(batch_page_info, batch_responses):
                    id_ = f"{lang}-{page_id}-{revision_id}"
                    page_type, title = page_info[(lang, page_id, revision_id)]

                    if response is None:
                        logger.debug(
                            "GET request failed: lang={}, page_id={}, revision_id={}, title={}",
                            lang,
                            page_id,
                            revision_id,
                            title,
                        )
                        continue

                    html = response.text.strip()
                    if html == "":
                        logger.debug(
                            "HTML is empty: lang={}, page_id={}, revision_id={}, title={}",
                            lang,
                            page_id,
                            revision_id,
                            title,
                        )
                        continue
                    if "bot-traffic@wikimedia.org" in html:
                        logger.debug(
                            "Possibly reached the API rate limit: lang={}, page_id={}, revision_id={}, title={}",
                            lang,
                            page_id,
                            revision_id,
                            title,
                        )
                        sleep(10)
                        continue

                    output_example = {
                        "id": id_,
                        "lang": lang,
                        "page_id": page_id,
                        "revision_id": revision_id,
                        "page_type": page_type,
                        "title": title,
                        "html": html,
                        "html_source": html_source,
                    }
                    print(json.dumps(output_example, ensure_ascii=False), file=fo)

                    num_examples += 1
                    remaining_page_info.pop((lang, page_id, revision_id))

                pbar.update(len(batch_page_info))
                batch_page_info = []
                batch_requests = []
                batch_responses = []

    return num_examples, remaining_page_info


def create_page_html_dataset_with_transform_wikitext_to_html_api(
    page_info: dict[tuple[str, int, int], tuple[str, str]],
    wikitexts: dict[tuple[str, int, int], str],
    output_file: str,
    user_agent: str,
    transform_to_mobile_html: bool = False,
    subst_query_title: str | None = None,
    request_batch_size: int = 1,
    timeout: int = 60,
) -> tuple[int, dict[tuple[str, int, int], tuple[str, str]]]:
    headers = {"User-Agent": user_agent}
    if transform_to_mobile_html:
        if subst_query_title is not None:
            html_source = "transform_wikitext_to_mobile_html_subst_query_title"
        else:
            html_source = "transform_wikitext_to_mobile_html"
    else:
        html_source = "transform_wikitext_to_html"

    num_examples = 0
    remaining_page_info = page_info.copy()  # (lang, page_id, revision_id) -> (page_type, title)

    Path(output_file).parent.mkdir(parents=True, exist_ok=True)

    with gzip.open(output_file, "at") as fo, tqdm(total=len(page_info)) as pbar:
        batch_page_info = []
        batch_requests = []

        for idx, (lang, page_id, revision_id) in enumerate(page_info):
            page_type, title = page_info[(lang, page_id, revision_id)]

            if transform_to_mobile_html:
                if subst_query_title is not None:
                    query_title = quote(subst_query_title.replace(" ", "_"), safe="")
                else:
                    query_title = quote(title.replace(" ", "_"), safe="")

                if page_type == PAGE_TYPE_CATEGORY:
                    query_title = "Category:" + query_title
                elif page_type == PAGE_TYPE_TEMPLATE:
                    query_title = "Template:" + query_title

                url = f"https://{lang}.wikipedia.org/api/rest_v1/transform/wikitext/to/mobile-html/{query_title}"
            else:
                url = f"https://{lang}.wikipedia.org/api/rest_v1/transform/wikitext/to/html"

            wikitext = wikitexts[(lang, page_id, revision_id)]
            post_data = {"wikitext": wikitext}

            batch_page_info.append((lang, page_id, revision_id))
            batch_requests.append(grequests.post(url, data=post_data, headers=headers, timeout=timeout))

            if len(batch_page_info) >= request_batch_size or idx == len(page_info) - 1:
                batch_responses = grequests.map(batch_requests)
                assert len(batch_page_info) == len(batch_requests) == len(batch_responses)

                for (lang, page_id, revision_id), response in zip(batch_page_info, batch_responses):
                    id_ = f"{lang}-{page_id}-{revision_id}"
                    page_type, title = page_info[(lang, page_id, revision_id)]

                    if response is None:
                        logger.debug(
                            "POST request failed: lang={}, page_id={}, revision_id={}, title={}",
                            lang,
                            page_id,
                            revision_id,
                            title,
                        )
                        continue

                    html = response.text.strip()
                    if html == "":
                        logger.debug(
                            "HTML is empty: lang={}, page_id={}, revision_id={}, title={}",
                            lang,
                            page_id,
                            revision_id,
                            title,
                        )
                        continue
                    if "bot-traffic@wikimedia.org" in html:
                        logger.debug(
                            "Possibly reached the API rate limit: lang={}, page_id={}, revision_id={}, title={}",
                            lang,
                            page_id,
                            revision_id,
                            title,
                        )
                        sleep(10)
                        continue

                    if transform_to_mobile_html and subst_query_title is not None:
                        html = html.replace(subst_query_title, title)
                        html = html.replace(subst_query_title.replace(" ", "_"), title.replace(" ", "_"))
                        html = html.replace(quote(subst_query_title), quote(title))

                    output_example = {
                        "id": id_,
                        "lang": lang,
                        "page_id": page_id,
                        "revision_id": revision_id,
                        "page_type": page_type,
                        "title": title,
                        "html": html,
                        "html_source": html_source,
                    }
                    print(json.dumps(output_example, ensure_ascii=False), file=fo)

                    num_examples += 1
                    remaining_page_info.pop((lang, page_id, revision_id))

                pbar.update(len(batch_page_info))
                batch_page_info = []
                batch_requests = []
                batch_responses = []

    return num_examples, remaining_page_info


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--page_dataset_file", type=str, required=True)
    parser.add_argument("--output_file", type=str, required=True)
    parser.add_argument("--enterprise_html_files", nargs="+", type=str)
    parser.add_argument("--get_page_html", action="store_true")
    parser.add_argument("--get_page_mobile_html", action="store_true")
    parser.add_argument("--transform_wikitext_to_html", action="store_true")
    parser.add_argument("--transform_wikitext_to_mobile_html", action="store_true")
    parser.add_argument("--transform_wikitext_to_mobile_html_subst_query_title", action="store_true")
    parser.add_argument("--user_agent", type=str)
    parser.add_argument("--get_latest_revision", action="store_true")
    parser.add_argument("--subst_query_title", type=str, default="Main Page")
    parser.add_argument("--get_request_batch_size", type=int, default=1)
    parser.add_argument("--transform_request_batch_size", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--max_retries", type=int, default=10)
    parser.add_argument("--page_dataset_ids", nargs="+", type=str)
    args = parser.parse_args()

    if Path(args.output_file).exists():
        raise FileExistsError(args.output_file)

    if args.user_agent is None and any(
        (
            args.get_page_html,
            args.get_page_mobile_html,
            args.transform_wikitext_to_html,
            args.transform_wikitext_to_mobile_html,
            args.transform_wikitext_to_mobile_html_subst_query_title,
        )
    ):
        raise ValueError("user_agent needs to be specified in order to use Wikimedia REST API")

    logger.info("Loading page information from the page dataset")
    page_info = load_page_info_from_page_dataset(args.page_dataset_file, page_dataset_ids=args.page_dataset_ids)

    total_num_examples = 0

    if len(page_info) > 0 and args.enterprise_html_files is not None:
        logger.info("Generating page HTML examples from Wikimedia Enterprise HTML dump files")
        num_examples, page_info = create_page_html_dataset_from_enterprise_html_files(
            args.enterprise_html_files, page_info, args.output_file
        )
        logger.debug("Number of generated examples: {}", num_examples)
        logger.debug("Number of remaining examples: {}", len(page_info))
        total_num_examples += num_examples

    if len(page_info) > 0 and args.get_page_html:
        for i in range(args.max_retries):
            sleep(10 * i)
            logger.info(
                "Generating page HTML examples using Wikimedia REST API to get page HTMLs ({}/{} iteration)",
                i + 1,
                args.max_retries,
            )
            num_examples, page_info = create_page_html_dataset_with_get_page_html_api(
                page_info,
                args.output_file,
                args.user_agent,
                get_latest_revision=args.get_latest_revision,
                request_batch_size=args.get_request_batch_size if i == 0 else 1,
                timeout=args.timeout,
            )
            logger.debug("Number of generated examples: {}", num_examples)
            logger.debug("Number of remaining examples: {}", len(page_info))
            total_num_examples += num_examples

            if len(page_info) == 0:
                break

    if len(page_info) > 0 and args.get_page_mobile_html:
        for i in range(args.max_retries):
            sleep(10 * i)
            logger.info(
                "Generating page HTML examples using Wikimedia REST API to get mobile page HTMLs ({}/{} iteration)",
                i + 1,
                args.max_retries,
            )
            num_examples, page_info = create_page_html_dataset_with_get_page_html_api(
                page_info,
                args.output_file,
                args.user_agent,
                get_mobile_html=True,
                get_latest_revision=args.get_latest_revision,
                request_batch_size=args.get_request_batch_size if i == 0 else 1,
                timeout=args.timeout,
            )
            logger.debug("Number of generated examples: {}", num_examples)
            logger.debug("Number of remaining examples: {}", len(page_info))
            total_num_examples += num_examples

            if len(page_info) == 0:
                break

    if len(page_info) > 0 and any(
        (
            args.transform_wikitext_to_html,
            args.transform_wikitext_to_mobile_html,
            args.transform_wikitext_to_mobile_html_subst_query_title,
        )
    ):
        logger.info("Loading page wikitexts from the page dataset")
        wikitexts = load_wikitexts_from_page_dataset(args.page_dataset_file, page_info)

        if len(page_info) > 0 and args.transform_wikitext_to_html:
            for i in range(args.max_retries):
                sleep(10 * i)
                logger.info(
                    "Generating page HTML examples using Wikimedia REST API to transform wikitexts to HTMLs "
                    "({}/{} iteration)",
                    i + 1,
                    args.max_retries,
                )
                num_examples, page_info = create_page_html_dataset_with_transform_wikitext_to_html_api(
                    page_info,
                    wikitexts,
                    args.output_file,
                    args.user_agent,
                    request_batch_size=args.transform_request_batch_size if i == 0 else 1,
                    timeout=args.timeout,
                )
                logger.debug("Number of generated examples: {}", num_examples)
                logger.debug("Number of remaining examples: {}", len(page_info))
                total_num_examples += num_examples

                if len(page_info) == 0:
                    break

        if len(page_info) > 0 and args.transform_wikitext_to_mobile_html:
            for i in range(args.max_retries):
                sleep(10 * i)
                logger.info(
                    "Generating page HTML examples using Wikimedia REST API to transform wikitexts to mobile HTMLs "
                    "({}/{} iteration)",
                    i + 1,
                    args.max_retries,
                )
                num_examples, page_info = create_page_html_dataset_with_transform_wikitext_to_html_api(
                    page_info,
                    wikitexts,
                    args.output_file,
                    args.user_agent,
                    transform_to_mobile_html=True,
                    request_batch_size=args.transform_request_batch_size if i == 0 else 1,
                    timeout=args.timeout,
                )
                logger.debug("Number of generated examples: {}", num_examples)
                logger.debug("Number of remaining examples: {}", len(page_info))
                total_num_examples += num_examples

                if len(page_info) == 0:
                    break

        if len(page_info) > 0 and args.transform_wikitext_to_mobile_html_subst_query_title:
            for i in range(args.max_retries):
                sleep(10 * i)
                logger.info(
                    "Generating page HTML examples using Wikimedia REST API to transform wikitexts to mobile HTMLs "
                    'using the substituted query title "{}" ({}/{} iteration)',
                    args.subst_query_title,
                    i + 1,
                    args.max_retries,
                )
                num_examples, page_info = create_page_html_dataset_with_transform_wikitext_to_html_api(
                    page_info,
                    wikitexts,
                    args.output_file,
                    args.user_agent,
                    transform_to_mobile_html=True,
                    subst_query_title=args.subst_query_title,
                    request_batch_size=args.transform_request_batch_size if i == 0 else 1,
                    timeout=args.timeout,
                )
                logger.debug("Number of generated examples: {}", num_examples)
                logger.debug("Number of remaining examples: {}", len(page_info))
                total_num_examples += num_examples

                if len(page_info) == 0:
                    break

    for (lang, page_id, revision_id), (_, title) in page_info.items():
        logger.warning(
            "Failed to obtain page HTML: lang={}, page_id={}, revision_id={} title={}",
            lang,
            page_id,
            revision_id,
            title,
        )

    logger.info("Finished creating dataset of {} examples", total_num_examples)


if __name__ == "__main__":
    main()
