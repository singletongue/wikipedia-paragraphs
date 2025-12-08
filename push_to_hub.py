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

from datasets import Dataset
from loguru import logger


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset_dir", type=str, required=True)
    parser.add_argument("--repo_id", type=str, required=True)
    parser.add_argument("--config_name", type=str, required=True)
    parser.add_argument("--revisions", nargs="+", type=str, default=["main"])
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()

    logger.info("Loading dataset")
    dataset = Dataset.load_from_disk(args.dataset_dir)
    logger.debug("Number of examples: {}", len(dataset))

    for revision in args.revisions:
        logger.info("Pushing dataset to {} (config={}, revision={})", args.repo_id, args.config_name, revision)
        dataset.push_to_hub(args.repo_id, config_name=args.config_name, private=args.private, revision=revision)
        logger.info("Finished pushing dataset")


if __name__ == "__main__":
    main()
