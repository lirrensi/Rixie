# FILE: v2/pipeline.py
# PURPOSE: Hold minimal V2 pipeline wiring and LiteLLM request configuration helpers.
# OWNS: V2 stage orchestration skeleton and shared completion kwargs builder.
# EXPORTS: V2Pipeline, build_completion_kwargs.
# DOCS: README.md, v2/process.py, v2/schema.py

from __future__ import annotations

from dataclasses import dataclass

from litellm import completion

from v2.schema import BookArtifact, StageState


def build_completion_kwargs(model: str, messages: list[dict], temperature: float = 0.2) -> dict:
    return {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }


@dataclass
class V2Pipeline:
    model: str = "gpt-4o-mini"
    temperature: float = 0.2

    def preview_request(self, artifact: BookArtifact, stage_name: str) -> dict:
        return build_completion_kwargs(
            model=self.model,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": f"Prepare V2 stage {stage_name}."},
                {"role": "user", "content": f"Book: {artifact.metadata.title}"},
            ],
        )

    def run_stage(self, artifact: BookArtifact, stage_name: str) -> BookArtifact:
        artifact.stages.setdefault(stage_name, StageState(name=stage_name, status="pending"))
        artifact.notes.append(
            f"TODO: stage '{stage_name}' not implemented yet; LiteLLM hook available via v2.pipeline."
        )
        return artifact.touch()


__all__ = ["V2Pipeline", "build_completion_kwargs", "completion"]
