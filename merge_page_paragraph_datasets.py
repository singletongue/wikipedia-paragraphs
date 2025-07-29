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
from pathlib import Path

from datasets import Features, Value, concatenate_datasets, load_dataset
from logzero import logger


PAGE_DATASET_FEATURES = Features(
    {
        "id": Value("string"),
        "lang": Value("string"),
        "page_id": Value("int64"),
        "revision_id": Value("int64"),
        "page_type": Value("string"),
        "title": Value("string"),
        "wikidata_qid": Value("string"),
        "wikitext": Value("string"),
        "linked_articles": [Value("string")],
        "categories": [Value("string")],
        "templates": [Value("string")],
        "num_inlinks": Value("int64"),
        "redirects": [Value("string")],
    }
)

PARAGRAPH_DATASET_FEATURES = Features(
    {
        "id": Value("string"),
        "lang": Value("string"),
        "page_id": Value("int64"),
        "revision_id": Value("int64"),
        "page_type": Value("string"),
        "title": Value("string"),
        "paragraph_texts": [Value("string")],
        "paragraph_sections": [Value("string")],
        "paragraph_wikilinks": [
            [
                {
                    "lang": Value("string"),
                    "title": Value("string"),
                    "text": Value("string"),
                    "start": Value("int64"),
                    "end": Value("int64"),
                }
            ]
        ],
        "paragraph_html_tags": [Value("string")],
    }
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--page_dataset_file", type=str, required=True)
    parser.add_argument("--paragraph_dataset_dir", type=str, required=True)
    parser.add_argument("--output_dir", type=str, required=True)
    parser.add_argument("--cache_dir", type=str)
    parser.add_argument("--num_processes", type=int)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logger.setLevel("DEBUG" if args.debug else "INFO")

    if Path(args.output_dir).exists():
        raise FileExistsError(args.output_dir)

    logger.info("Loading page dataset")
    page_dataset = load_dataset(
        "json",
        data_files=args.page_dataset_file,
        split="train",
        cache_dir=args.cache_dir,
        features=PAGE_DATASET_FEATURES,
    )
    num_page_dataset_examples = len(page_dataset)
    logger.debug("Number of examples in page dataset: %d", num_page_dataset_examples)

    logger.info("Loading paragraph dataset")
    paragraph_dataset = load_dataset(
        "json",
        data_dir=args.paragraph_dataset_dir,
        split="train",
        cache_dir=args.cache_dir,
        features=PARAGRAPH_DATASET_FEATURES,
        num_proc=args.num_processes,
    )
    num_paragraph_dataset_examples = len(paragraph_dataset)
    logger.debug("Number of examples in paragraph dataset: %d", num_paragraph_dataset_examples)

    if num_page_dataset_examples != num_paragraph_dataset_examples:
        raise RuntimeError(
            "Page and paragraph datasets have different number of examples "
            f"({num_page_dataset_examples} != {num_paragraph_dataset_examples})"
        )

    logger.info("Sorting and merging datasets")
    page_dataset = page_dataset.sort("page_id")
    paragraph_dataset = paragraph_dataset.sort("page_id")
    merged_dataset = concatenate_datasets(
        [
            page_dataset.select_columns(
                ["id", "lang", "page_id", "revision_id", "page_type", "title", "wikidata_qid"]
            ),
            paragraph_dataset.select_columns(
                ["paragraph_texts", "paragraph_sections", "paragraph_wikilinks", "paragraph_html_tags"]
            ),
            page_dataset.select_columns(["linked_articles", "categories", "templates", "num_inlinks", "redirects"]),
        ],
        axis=1,
    )

    logger.info("Saving merged dataset to disk")
    merged_dataset.save_to_disk(args.output_dir, num_proc=args.num_processes)


if __name__ == "__main__":
    main()
