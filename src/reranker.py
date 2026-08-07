from __future__ import annotations

from collections.abc import Sequence


MODEL_ID = "BAAI/bge-reranker-v2-m3"


def dependencies_available() -> bool:
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        return False
    return True


class BGEReranker:
    def __init__(self, model_id: str = MODEL_ID) -> None:
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "Reranker 의존성이 없습니다. requirements-reranker.txt를 설치해 주세요."
            ) from exc

        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(model_id)
        self._model = AutoModelForSequenceClassification.from_pretrained(model_id)
        if torch.cuda.is_available():
            self._device = torch.device("cuda")
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            self._device = torch.device("mps")
        else:
            self._device = torch.device("cpu")
        self._model.to(self._device)
        self._model.eval()

    def score(
        self,
        query: str,
        documents: Sequence[str],
        batch_size: int = 8,
    ) -> list[float]:
        torch = self._torch
        output_scores: list[float] = []
        pairs = [[query, document] for document in documents]
        for start in range(0, len(pairs), batch_size):
            batch = pairs[start : start + batch_size]
            inputs = self._tokenizer(
                [pair[0] for pair in batch],
                [pair[1] for pair in batch],
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            )
            inputs = {key: value.to(self._device) for key, value in inputs.items()}
            with torch.inference_mode():
                logits = self._model(**inputs).logits.view(-1)
                scores = torch.sigmoid(logits).detach().float().cpu().tolist()
            output_scores.extend(float(score) for score in scores)
        return output_scores
