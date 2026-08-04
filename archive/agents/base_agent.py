"""Agent 基类"""
import logging
from abc import ABC, abstractmethod
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)


class BaseAgent(ABC):
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(name)

    @abstractmethod
    async def run(self, *args, **kwargs) -> Any:
        ...

    def log(self, msg: str):
        self.logger.info(msg)

    def warn(self, msg: str):
        self.logger.warning(msg)
