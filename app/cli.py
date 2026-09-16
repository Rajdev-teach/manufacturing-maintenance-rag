from __future__ import annotations

from app.config import load_settings
from app.local_rag import LocalRAG


def main() -> None:
    settings = load_settings()
    if settings.backend != "local":
        raise SystemExit("Use scripts/demo_openai.py for the OpenAI/FAISS backend.")
    rag = LocalRAG.from_directory(settings.root / "data" / "clean", settings.top_k)
    history: list[tuple[str, str]] = []
    print("Manufacturing RAG Assistant — type 'exit' to quit")
    while True:
        question = input("\nYou: ").strip()
        if question.lower() in {"exit", "quit"}:
            break
        response = rag.ask(question, history)
        print(f"\nAssistant: {response['answer']}")
        if response["sources"]:
            print("Sources:")
            for source in response["sources"]:
                print(f"- [{source['id']}] {source['title']} ({source['source']})")
        history.append((question, response["answer"]))


if __name__ == "__main__":
    main()

