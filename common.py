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
import re
from html import unescape
from urllib.parse import unquote


NAMESPACE_ARTICLE = 0
NAMESPACE_CATEGORY = 14
NAMESPACE_TEMPLATE = 10

PAGE_TYPE_ARTICLE = "article"
PAGE_TYPE_CATEGORY = "category"
PAGE_TYPE_TEMPLATE = "template"


def capitalize_first_letter(text: str) -> str:
    # Capitalize single-byte characters only
    if len(text) > 0 and len(text[0].encode()) == 1:
        return text[0].upper() + text[1:]
    else:
        return text


def normalize_title(title: str) -> str:
    title = unescape(title)  # e.g., d&eacute;partement -> département
    title = unquote(title)  # e.g., %40 -> @

    title = title.split("|")[0]
    title = title.split("#")[0]

    title = title.replace("_", " ")
    title = re.sub(r"\s+", " ", title)
    title = title.strip()

    title = capitalize_first_letter(title)

    return title


def get_page_type_from_namespace(namespace: int) -> str:
    if namespace == NAMESPACE_ARTICLE:
        return PAGE_TYPE_ARTICLE
    elif namespace == NAMESPACE_CATEGORY:
        return PAGE_TYPE_CATEGORY
    elif namespace == NAMESPACE_TEMPLATE:
        return PAGE_TYPE_TEMPLATE
    else:
        raise ValueError(f"Unexpected namespace: {namespace}")
