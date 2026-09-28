# Architecture and UML diagrams

The service has two RAG backends. `local` retrieves with TF-IDF and composes an extractive answer without credentials. `openai` embeds documents once at startup, uses a FAISS index to retrieve chunks, and generates a grounded answer with the configured chat model. Both return source IDs from the approved corpus.

## System flowchart

```mermaid
flowchart TD
    A["Client question"] --> B["FastAPI validation"]
    B --> C{"RAG_BACKEND"}
    C -->|local| D["TF-IDF retrieval and extractive answer"]
    C -->|openai| E["FAISS retrieval and chat generation"]
    D --> F["Answer, citations, and timings"]
    E --> F
    F --> G["MLflow run: parameters, metrics, artifact"]
    F --> H["HTTP response"]
    G -.->|tracking failure| H
```

## UML sequence diagram

```mermaid
sequenceDiagram
    actor Client
    participant API as FastAPI
    participant RAG as RAG service
    participant Tracker as Tracking helper
    participant MLflow
    Client->>API: POST /query(question, top_k)
    API->>API: Validate input
    API->>RAG: ask(question, top_k)
    RAG->>RAG: Retrieve and time chunks
    RAG->>RAG: Compose and time answer
    RAG-->>API: Answer, citations, phase timings
    API->>Tracker: Log run and interaction
    Tracker->>MLflow: Parameters, metrics, artifact
    alt Tracking succeeds
        MLflow-->>Tracker: Run stored
    else Tracking fails
        Tracker->>Tracker: Log warning
    end
    Tracker-->>API: logged or unavailable
    API-->>Client: Answer and metadata
```

## UML activity diagram

```mermaid
flowchart TD
    Start(["Receive query"]) --> Valid{"Question valid?"}
    Valid -->|no| Error(["400 or 422 response"])
    Valid -->|yes| Retrieve["Retrieve document chunks"]
    Retrieve --> Found{"Evidence found?"}
    Found -->|no| Refuse["Return grounded refusal"]
    Found -->|yes| Answer["Generate or extract answer"]
    Refuse --> Track["Attempt MLflow logging"]
    Answer --> Track
    Track --> Finish(["Return answer, citations, timings"])
```

## UML class diagram

```mermaid
classDiagram
    class API {
        +health()
        +info()
        +query(request)
    }
    class QueryRequest {
        +str question
        +int top_k
    }
    class QueryResponse {
        +str answer
        +SourceCitation[] sources
        +QueryMetadata metadata
    }
    class LocalService {
        +ask(question, top_k) Answer
    }
    class OpenAIService {
        +ask(question, top_k) Answer
    }
    class InferenceTracker {
        +log(inference) str
    }
    API --> QueryRequest
    API --> QueryResponse
    API --> LocalService
    API --> OpenAIService
    API --> InferenceTracker
```

## Metadata and boundaries

- Source metadata is limited to chunk ID, document title, and filename. The manifest in `data/manifest.csv` records corpus ownership and dates.
- API metadata contains a generated request ID, actual backend and model, service version, measured phases, and whether tracking succeeded. It never exposes API keys or local filesystem paths.
- MLflow persists each question and answer in `interaction.json`. Use this educational corpus and avoid sending sensitive operational or personal data without a retention and access policy.
- Docker Compose binds the two ports to localhost and uses a named volume for SQLite and artifacts. Production use needs authentication, encrypted transport, access controls, and a more robust backing store.
