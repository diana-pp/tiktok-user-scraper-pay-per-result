import argparse
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

# Ensure local src directory is importable when running as a script
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from extractors.tiktok_parser import TikTokUser, parse_user_from_url  # type: ignore
from extractors.utils_network import create_http_session  # type: ignore
from outputs.exporters import export_data  # type: ignore

DEFAULT_CONFIG_PATH = os.path.join(CURRENT_DIR, "config", "settings.example.json")
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, os.pardir))
DEFAULT_INPUT_PATH = os.path.join(PROJECT_ROOT, "data", "inputs.sample.txt")
DEFAULT_OUTPUT_PATH = os.path.join(PROJECT_ROOT, "data", "sample_output.json")

def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] [%(levelname)s] %(name)s - %(message)s",
    )

def load_config(path: str) -> Dict[str, Any]:
    logger = logging.getLogger("config")
    if not os.path.exists(path):
        logger.warning("Config file '%s' not found. Using built-in defaults.", path)
        return {
            "output_format": "json",
            "max_workers": 5,
            "request_timeout": 10,
            "retry_attempts": 1,
        }

    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        logger.info("Loaded config from %s", path)
        return cfg
    except Exception as exc:
        logger.error("Failed to load config %s: %s", path, exc)
        return {
            "output_format": "json",
            "max_workers": 5,
            "request_timeout": 10,
            "retry_attempts": 1,
        }

def load_inputs(path: str) -> List[str]:
    logger = logging.getLogger("inputs")
    if not os.path.exists(path):
        logger.error("Input file '%s' does not exist.", path)
        return []

    urls: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            urls.append(stripped)

    logger.info("Loaded %d input URLs from %s", len(urls), path)
    return urls

def scrape_users(
    urls: List[str],
    config: Dict[str, Any],
) -> List[Dict[str, Any]]:
    logger = logging.getLogger("scraper")

    if not urls:
        logger.warning("No URLs to process.")
        return []

    max_workers = int(config.get("max_workers", 5))
    request_timeout = int(config.get("request_timeout", 10))
    retry_attempts = int(config.get("retry_attempts", 1))

    session = create_http_session()

    results: List[Dict[str, Any]] = []
    futures = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for url in urls:
            future = executor.submit(
                parse_user_from_url,
                url=url,
                session=session,
                timeout=request_timeout,
                retries=retry_attempts,
            )
            futures.append(future)

        for future in as_completed(futures):
            try:
                user: Optional[TikTokUser] = future.result()
                if user is not None:
                    results.append(user.to_dict())
            except Exception as exc:
                logger.error("Unexpected error while scraping a URL: %s", exc)

    logger.info("Successfully scraped %d/%d URLs", len(results), len(urls))
    return results

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="TikTok User Scraper - Pay Per Result demo runner"
    )
    parser.add_argument(
        "--input",
        "-i",
        default=DEFAULT_INPUT_PATH,
        help="Path to input file containing TikTok profile or video URLs (one per line).",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=DEFAULT_OUTPUT_PATH,
        help="Path to output file (.json or .csv).",
    )
    parser.add_argument(
        "--config",
        "-c",
        default=DEFAULT_CONFIG_PATH,
        help="Path to JSON config file.",
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["json", "csv"],
        help="Output format. Overrides config file if set.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging.",
    )
    return parser

def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)
    logger = logging.getLogger("runner")

    config = load_config(args.config)
    if args.format:
        config["output_format"] = args.format

    urls = load_inputs(args.input)
    if not urls:
        logger.error("Aborting: no valid input URLs.")
        sys.exit(1)

    logger.info("Starting TikTok user scraping for %d URLs", len(urls))
    data = scrape_users(urls, config)

    if not data:
        logger.warning("No data scraped; output file will contain an empty list.")

    export_data(
        records=data,
        output_path=args.output,
        output_format=config.get("output_format"),
    )

    logger.info("All done. Wrote %d records to %s", len(data), args.output)

if __name__ == "__main__":
    main()