# wikipedia-paragraphs

`wikipedia-paragraphs` is a dataset generated from Wikipedia, designed for natural language processing (NLP) research.

The dataset is available on [Hugging Face Hub](https://huggingface.co/datasets/singletongue/wikipedia-paragraphs).

This repository contains the code used to create the dataset.
For details about the dataset itself, including its specifications and usage examples, please refer to the Hugging Face Hub page.

## Dataset creation process

The following steps outline the procedure for creating the `**wiki-20261101-v1.3.0` configuration of the dataset, which is available on Hugging Face Hub.
In this context, `**` represents the language codes for the 11 target languages: `ar`, `de`, `en`, `es`, `fr`, `it`, `ja`, `ko`, `pt`, `ru`, and `zh`.

The process was run on a Linux machine with 128GB of RAM.

### Download dump files

For the 11 target languages, download the following dump files and save them to the `data/` directory:

- [Wikipedia Cirrussearch dumps](https://dumps.wikimedia.org/other/cirrus_search_index/):
  - Download the `**wiki_content-20261101-*****.json.bz2` and `**wiki_general-20261101-*****.json.bz2` files.
- [Wikimedia Enterprise API](https://enterprise.wikimedia.com/) (sign-up required):
  - Use the [Snapshot API](https://enterprise.wikimedia.com/docs/snapshot/) to download the `**wiki_namespace_0`, `**wiki_namespace_10`, and `**wiki_namespace_14` snapshots (saved as `**wiki_namespace_0.tar.gz`, `**wiki_namespace_10.tar.gz`, and `**wiki_namespace_14.tar.gz`, respectively).

### Set up virtual environment

[uv](https://github.com/astral-sh/uv) (v0.13.6) is used.

```sh
uv sync --locked
```

### Create page datasets

> [!IMPORTANT]
> This step queries the [MediaWiki Action API](https://www.mediawiki.org/wiki/API:Action_API) to retrieve category aliases for each language's Wikipedia.
> Please be sure to consult the API's web page for its terms of use.

> [!NOTE]
> Please refer to [this page](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy) for setting a valid user agent.

```sh
for WIKILANG in ar de en es fr it ja ko pt ru zh; do \
uv run create_page_dataset.py \
--cirrussearch_files \
  data/${WIKILANG}wiki_content-20261101-*.json.bz2 \
  data/${WIKILANG}wiki_general-20261101-*.json.bz2 \
--output_file work/${WIKILANG}wiki-20261101-pages.jsonl.gz \
--lang ${WIKILANG} \
--user_agent <valid user agent> \
--num_processes 8; \
done
```

### Create page HTML datasets

> [!IMPORTANT]
> This step queries the [Wikimedia REST API](https://www.mediawiki.org/wiki/Wikimedia_REST_API) to fetch article HTMLs missing from the dump files.
> Please be sure to consult the API's web page for its terms of use and check the latest information on [rate limits](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits).

> [!NOTE]
> Please refer to [this page](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy) for setting a valid user agent.

```sh
for WIKILANG in ar de en es fr it ja ko pt ru zh; do \
uv run create_page_html_dataset.py \
--page_dataset_file work/${WIKILANG}wiki-20261101-pages.jsonl.gz \
--output_file work/${WIKILANG}wiki-20261101-page-htmls.jsonl.gz \
--enterprise_html_files \
  data/${WIKILANG}wiki_namespace_0.tar.gz \
  data/${WIKILANG}wiki_namespace_10.tar.gz \
  data/${WIKILANG}wiki_namespace_14.tar.gz \
--get_page_html \
--transform_wikitext_to_html \
--user_agent <valid user agent> \
--get_request_batch_size 1 \
--transform_request_batch_size 1; \
done
```

<!-- ### Create page HTML datasets (mobile version)

```sh
for WIKILANG in ar de en es fr it ja ko pt ru zh; do \
uv run create_page_html_dataset.py \
--page_dataset_file work/${WIKILANG}wiki-20261101-pages.jsonl.gz \
--output_file work/${WIKILANG}wiki-20261101-page-htmls.jsonl.gz \
--enterprise_html_files \
  data/${WIKILANG}wiki_namespace_0.tar.gz \
  data/${WIKILANG}wiki_namespace_10.tar.gz \
  data/${WIKILANG}wiki_namespace_14.tar.gz \
--get_page_mobile_html \
--transform_wikitext_to_mobile_html \
--transform_wikitext_to_mobile_html_subst_query_title \
--user_agent <valid user agent> \
--subst_query_title メインページ \
--get_request_batch_size 1 \
--transform_request_batch_size 1; \
done
``` -->

### Create paragraph datasets

```sh
for WIKILANG in ar de en es fr it ja ko pt ru zh; do \
uv run create_paragraph_dataset.py \
--page_dataset_files work/*wiki-20261101-pages.jsonl.gz \
--page_html_dataset_files work/${WIKILANG}wiki-20261101-page-htmls.jsonl.gz \
--output_dir work/${WIKILANG}wiki-20261101-paragraphs \
--paragraph_tags p li dt dd blockquote \
--article_redirects_file work/article-redirects-20261101.pkl \
--num_processes 4; \
done
```

<!-- ```sh
for WIKILANG in ar de en es fr it ja ko pt ru zh; do \
uv run create_paragraph_dataset.py \
--page_dataset_files work/*wiki-20261101-pages.jsonl.gz \
--page_html_dataset_files work/${WIKILANG}wiki-20261101-page-htmls.jsonl.gz \
--output_dir work/${WIKILANG}wiki-20261101-paragraphs \
--paragraph_tags p li dt dd blockquote \
--add_pseudo_self_wikilinks \
--article_redirects_file work/article-redirects-20261101.pkl \
--num_processes 4; \
done
``` -->

### Merge page and paragraph datasets

```sh
for WIKILANG in ar de en es fr it ja ko pt ru zh; do \
uv run merge_page_paragraph_datasets.py \
--page_dataset_file work/${WIKILANG}wiki-20261101-pages.jsonl.gz \
--paragraph_dataset_dir work/${WIKILANG}wiki-20261101-paragraphs \
--output_dir outputs/${WIKILANG}wiki-20261101 \
--cache_dir cache \
--num_processes 4 \
&& rm -r cache; \
done
```

> [!NOTE]
> For primary languages like `en`, the `cache/` directory can grow to hundreds of gigabytes in size.

### Push merged datasets to Hugging Face Hub

```sh
for WIKILANG in ar de en es fr it ja ko pt ru zh; do \
uv run push_to_hub.py \
--dataset_dir outputs/${WIKILANG}wiki-20261101 \
--repo_id <your dataset repo id (e.g., singletongue/wikipedia-paragraphs)> \
--config_name ${WIKILANG}wiki-20261101-v1.3.0; \
done
```

## License

- Code: [Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0)
- Datasets: [CC-BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) and [GFDL](https://www.gnu.org/copyleft/fdl.html)
