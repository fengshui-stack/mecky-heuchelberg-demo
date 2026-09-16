"""Typed runtime configuration for the model-led Mecky agent."""
import json
import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class StrictConfig(BaseModel):
    model_config=ConfigDict(extra="forbid")


class LLMConfig(StrictConfig):
    provider: str="openai"
    model: str="gpt-5-mini"
    temperature: float=.7
    max_tokens: int=Field(default=400,ge=50,le=2000)
    timeout_seconds: float=Field(default=15,gt=0,le=120)
    retries: int=Field(default=2,ge=1,le=3)


class ToolsConfig(StrictConfig):
    strict_schemas: bool=True
    parallel_tool_calls: bool=True
    max_tools_per_request: int=Field(default=20,ge=1,le=20)
    max_tool_rounds: int=Field(default=3,ge=1,le=5)


class ValidatorConfig(StrictConfig):
    enabled: bool=True
    llm_judge_model: str="gpt-5-mini"
    max_retries: int=Field(default=2,ge=1,le=3)
    pass_on_uncertainty: bool=True


class StreamingConfig(StrictConfig):
    enabled: bool=True
    transport: str="sse"


class AppConfig(StrictConfig):
    llm: LLMConfig
    tools: ToolsConfig
    validator: ValidatorConfig
    streaming: StreamingConfig


@lru_cache(maxsize=1)
def load_config()->AppConfig:
    raw=json.loads(Path(__file__).with_name("config.yaml").read_text(encoding="utf-8"))
    raw["llm"]["provider"]=os.getenv("LLM_PROVIDER",raw["llm"]["provider"])
    raw["llm"]["model"]=os.getenv("LLM_MODEL",raw["llm"]["model"])
    raw["validator"]["llm_judge_model"]=os.getenv("LLM_VALIDATOR_MODEL",raw["validator"]["llm_judge_model"])
    return AppConfig.model_validate(raw)
