import os
import sys
import logging
from omegaconf import DictConfig
import hydra
from loguru import logger
import dotenv
from zotero_arxiv_daily.executor import Executor
from omegaconf import open_dict
os.environ["TOKENIZERS_PARALLELISM"] = "false"
dotenv.load_dotenv()


def apply_runtime_env_overrides(config: DictConfig) -> None:
    with open_dict(config):
        arxiv_query = os.getenv("ARXIV_QUERY")
        if arxiv_query:
            config.source.arxiv.category = [
                item.strip()
                for item in arxiv_query.replace(",", "+").split("+")
                if item.strip()
            ]
        max_paper_num = os.getenv("MAX_PAPER_NUM")
        if max_paper_num:
            config.executor.max_paper_num = int(max_paper_num)
        model_name = os.getenv("MODEL_NAME")
        if model_name:
            config.llm.generation_kwargs.model = model_name
        language = os.getenv("LANGUAGE")
        if language:
            config.llm.language = language
        debug = os.getenv("DEBUG")
        if debug:
            config.executor.debug = debug.lower() in {"1", "true", "yes", "on"}

@hydra.main(version_base=None, config_path="../../config", config_name="default")
def main(config:DictConfig):
    apply_runtime_env_overrides(config)
    # Configure loguru log level based on config
    log_level = "DEBUG" if config.executor.debug else "INFO"
    logger.remove()  # Remove default handler
    logger.add(
        sys.stdout,
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )
    
    for logger_name in logging.root.manager.loggerDict:
        if "zotero_arxiv_daily" in logger_name:
            continue
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    if config.executor.debug:
        logger.info("Debug mode is enabled")
    
    executor = Executor(config)
    executor.run()

if __name__ == '__main__':
    main()
