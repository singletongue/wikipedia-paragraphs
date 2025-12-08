# wikipedia-paragraphs

`wikipedia-paragraphs` is a dataset generated from Wikipedia, designed for natural language processing (NLP) research.

The dataset is available on [Hugging Face Hub](https://huggingface.co/datasets/singletongue/wikipedia-paragraphs).

This repository contains the code used to create the dataset.
For details about the dataset itself, including its specifications and usage examples, please refer to the Hugging Face Hub page.

## Dataset creation process

The following steps outline the procedure for creating the `**wiki-20250901` configuration of the dataset, which is available on Hugging Face Hub.
In this context, `**` represents the language codes for the 11 target languages: `ar`, `de`, `en`, `es`, `fr`, `it`, `ja`, `ko`, `pt`, `ru`, and `zh`.

The process was run on a Linux machine with 128GB of RAM.

### Download dump files

For the 11 target languages, download the following dump files and save them to the `data/` directory:

- [Wikipedia Cirrussearch dumps](https://dumps.wikimedia.org/other/cirrussearch/):
  - For all 11 languages, download the `**wiki-20250901-cirrussearch-content.json.gz` and `**wiki-20250901-cirrussearch-general.json.gz` files.
- [Wikimedia Enterprise API](https://enterprise.wikimedia.com/) (sign-up required):
  - For all 11 languages, use the [Snapshot API](https://enterprise.wikimedia.com/docs/snapshot/) to download the `**wiki_namespace_0` snapshot (saved as `**wiki_namespace_0.tar.gz`).
  - Additionally, for English (`en`), download the `enwiki_namespace_10` and `enwiki_namespace_14` snapshots (saved as `enwiki_namespace_10.tar.gz` and `enwiki_namespace_14.tar.gz`, respectively).
- [Wikimedia Enterprise HTML dumps](https://dumps.wikimedia.org/other/enterprise_html/runs/):
  - For the 10 languages other than English (`en`), download the `**wiki-NS10-20250320-ENTERPRISE-HTML.json.tar.gz` and `**wiki-NS14-20250320-ENTERPRISE-HTML.json.tar.gz` files.

### Set up virtual environment

[uv](https://github.com/astral-sh/uv) (v0.8.15) is used.

```sh
uv sync
```

### Create page datasets

**Important:**
This step queries the [MediaWiki Action API](https://www.mediawiki.org/wiki/API:Action_API) to retrieve category aliases for each language's Wikipedia.
Please be sure to consult the API's web page for its terms of use.

```sh
for WIKILANG in ar de en es fr it ja ko pt ru zh; do \
uv run create_page_dataset.py \
--cirrussearch_files \
  data/${WIKILANG}wiki-20250901-cirrussearch-content.json.gz \
  data/${WIKILANG}wiki-20250901-cirrussearch-general.json.gz \
--output_file work/${WIKILANG}wiki-20250901-pages.jsonl.gz \
--lang ${WIKILANG} \
--user_agent <your email address> \
--num_processes 16; \
done
```

### Create page HTML datasets

**Important:**
This step queries the [Wikimedia REST API](https://www.mediawiki.org/wiki/Wikimedia_REST_API) to fetch article HTMLs missing from the dump files.
Please be sure to consult the API's web page for its terms of use.

```sh
# For English
uv run create_page_html_dataset.py \
--page_dataset_file work/enwiki-20250901-pages.jsonl.gz \
--output_file work/enwiki-20250901-page-htmls.jsonl.gz \
--enterprise_html_files \
  data/enwiki_namespace_0.tar.gz \
  data/enwiki_namespace_10.json.tar.gz \
  data/enwiki_namespace_14.json.tar.gz \
--get_page_html \
--transform_wikitext_to_html \
--user_agent <your email address> \
--get_request_batch_size 50 \
--transform_request_batch_size 50

# For the other 10 languages
for WIKILANG in ar de es fr it ja ko pt ru zh; do \
uv run create_page_html_dataset.py \
--page_dataset_file work/${WIKILANG}wiki-20250901-pages.jsonl.gz \
--output_file work/${WIKILANG}wiki-20250901-page-htmls.jsonl.gz \
--enterprise_html_files \
  data/${WIKILANG}wiki_namespace_0.tar.gz \
  data/${WIKILANG}wiki-NS10-20250320-ENTERPRISE-HTML.json.tar.gz \
  data/${WIKILANG}wiki-NS14-20250320-ENTERPRISE-HTML.json.tar.gz \
--get_page_html \
--transform_wikitext_to_html \
--user_agent <your email address> \
--get_request_batch_size 50 \
--transform_request_batch_size 50; \
done
```

<!-- ### Create page HTML datasets (mobile version)

```sh
for WIKILANG in ar de en es fr it ja ko pt ru zh; do \
uv run create_page_html_dataset.py \
--page_dataset_file work/${WIKILANG}wiki-20250901-pages.jsonl.gz \
--output_file work/${WIKILANG}wiki-20250901-page-htmls.jsonl.gz \
--enterprise_html_files \
  data/${WIKILANG}wiki-NS0-20250320-ENTERPRISE-HTML.json.tar.gz \
  data/${WIKILANG}wiki-NS10-20250320-ENTERPRISE-HTML.json.tar.gz \
  data/${WIKILANG}wiki-NS14-20250320-ENTERPRISE-HTML.json.tar.gz \
--get_page_mobile_html \
--transform_wikitext_to_mobile_html \
--transform_wikitext_to_mobile_html_subst_query_title \
--user_agent <your email address> \
--subst_query_title メインページ \
--get_request_batch_size 50 \
--transform_request_batch_size 50; \
done
``` -->

### Create paragraph datasets

```sh
for WIKILANG in ar de en es fr it ja ko pt ru zh; do \
uv run create_paragraph_dataset.py \
--page_dataset_files work/*wiki-20250901-pages.jsonl.gz \
--page_html_dataset_files work/${WIKILANG}wiki-20250901-page-htmls.jsonl.gz \
--output_dir work/${WIKILANG}wiki-20250901-paragraphs \
--paragraph_tags p li dt dd blockquote \
--article_redirects_file work/article-redirects-20250901.pkl \
--num_processes 4; \
done
```

<!-- ```sh
for WIKILANG in ar de en es fr it ja ko pt ru zh; do \
uv run create_paragraph_dataset.py \
--page_dataset_files work/*wiki-20250901-pages.jsonl.gz \
--page_html_dataset_files work/${WIKILANG}wiki-20250901-page-htmls.jsonl.gz \
--output_dir work/${WIKILANG}wiki-20250901-paragraphs \
--paragraph_tags p li dt dd blockquote \
--add_pseudo_self_wikilinks \
--article_redirects_file work/article-redirects-20250901.pkl \
--num_processes 4; \
done
``` -->

### Merge page and paragraph datasets

```sh
for WIKILANG in ar de en es fr it ja ko pt ru zh; do \
uv run merge_page_paragraph_datasets.py \
--page_dataset_file work/${WIKILANG}wiki-20250901-pages.jsonl.gz \
--paragraph_dataset_dir work/${WIKILANG}wiki-20250901-paragraphs \
--output_dir outputs/${WIKILANG}wiki-20250901 \
--cache_dir cache \
--num_processes 4 \
&& rm -r cache; \
done
```

**Note:** The data saved in the `cache/` directory is largest for English (`en`), requiring approximately 151GB of space.

### Push merged datasets to Hugging Face Hub

```sh
for WIKILANG in ar de en es fr it ja ko pt ru zh; do \
uv run push_to_hub.py \
--dataset_dir outputs/20250901/${WIKILANG}wiki-20250901 \
--repo_id <your dataset repo id (e.g., singletongue/wikipedia-paragraphs)> \
--config_name ${WIKILANG}wiki-20250901 \
--revisions v1.1.0 main; \
done
```

## License

- Code: [Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0)
- Datasets: [CC-BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) and [GFDL](https://www.gnu.org/copyleft/fdl.html)
