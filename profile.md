# George Pauly

Fullstack / Backend Software Engineer

- Email: georgepauly1995@gmail.com
- Phone: +91 8884562950
- GitHub: github.com/GeorgePauly95
- LinkedIn: linkedin.com/in/george-pauly

## Professional Summary

Backend Software Engineer with over four and a half years of experience designing high-performance Python web services, real-time data pipelines, and scalable AI integrations. Combines deep expertise in custom data engineering and complex relational databases to architect secure, data-intensive systems with a rigorous focus on structural integrity and system reliability.

## Technical Skills

- **Languages:** Python, SQL, JavaScript
- **Backend:** FastAPI, Django, Flask, RESTful APIs, WebSockets, async / asyncio, Pydantic
- **Data:** PostgreSQL, SQLAlchemy (ORM), Alembic, pgvector, Redis, MongoDB, OpenRefine
- **AI & Audio:** OpenRouter, WhisperX, Pyannote, Speech-to-Text
- **Auth:** OAuth2 / Google Sign-In, JWT
- **Infra & Tooling:** Docker, Render, Git, uv, pip, pytest, CI/CD
- **Frontend:** React, HTML, CSS

## Work Experience

### Software Engineer — Geekwerke Software, Bangalore

Feb 2025 – Present

#### AI-Powered Support Chat Widget

- Owned the backend messaging architecture for a live React-based support widget, engineering a low-latency FastAPI WebSocket layer supporting thousands of concurrent user sessions.
- Implemented a Retrieval-Augmented Generation (RAG) pipeline utilizing pgvector and OpenRouter to deliver context-aware AI draft responses, reducing average ticket resolution time by ~50%.
- Developed a hybrid search using pg text search , BM25,CosineSimilarityeSearch to help improve response quality by 50%.
- Integrated an automated speech-to-text transcription pipeline using Whisper to process voice queries directly into the text workflow.
- Maintained persistent user authentication across WebSocket connections by configuring Redis for rapid cookie validation and session state management.

#### GPS Data Tracking Pipeline

- Developed an asynchronous FastAPI tracking service that streamed live surveyor GPS data into PostgreSQL, reliably processing 50,000+ daily location pings from thousands of active daily users.
- Protected sensitive location streams by enforcing JWT validation and AES-encrypted session tokens on top of Google OAuth2 authentication.
- Managed database schema updates with Alembic and independently deployed the layered service to Render.
- Used NGINX as reverse proxy to route real time web socket messages and leveraged redis as message queue to handle 5x message traffic.
- Dockerised and cordinated between multiple microservices

### Lead Data Analyst — Clootrack Software Labs, Bangalore

Dec 2023 – Jan 2025

- Directed end-to-end data delivery architectures for over 15 enterprise clients, utilizing Python and SQL to automate dashboard generation and decrease manual reporting turnaround time by 40%.
- Managed data extraction and processing strategies, ensuring 99%+ data integrity and structural accuracy across all high-visibility client deliverables.

### Data Analyst — Clootrack Software Labs, Bangalore

June 2022 – Nov 2023

- Engineered and optimized custom Python web scraping and cleaning pipelines, successfully extracting and processing over 1 million unstructured data points monthly with high fault tolerance.
- Owned the end-to-end quality of programmatic data deliverables, coordinating directly with stakeholders to deliver structured datasets consistently ahead of schedule.

### Data Intern — Clootrack Software Labs, Bangalore

Feb 2022 – May 2022

- Developed Python scripts and utilized OpenRefine to extract, clean, and standardize large datasets containing 100,000+ records, reducing downstream analytics preparation time by 25%.

## Education

### Master of Science (M.Sc.) in Mathematics

Mysore University

### Bachelor of Science (B.Sc.) in Mathematics, Physics, and Electronics

Christ University
