# TeemUp-n8n

A Python service to fetch Meetup events for publishing to Discord channels via n8n.

## Setup

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd teemup
    ```

2.  **Configuration:**
    Copy the example configuration file:
    ```bash
    cp config.example.yaml config.yaml
    ```
    Edit `config.yaml` with your Meetup group URLs and preferences.

3.  **Install dependencies:**
    It is recommended to use a virtual environment.
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```

4.  **Run the application:**
    ```bash
    uvicorn app:app --reload
    ```
    The API will be available at `http://localhost:8000`.

## Docker

### Build

```bash
docker build -t teemup-n8n .
```

### Run

```bash
docker run -d -p 8080:8080 --name teemup-n8n teemup-n8n
```

The service will be available at `http://localhost:8080`.

## Configuration

The application is configured via `config.yaml`. See `config.example.yaml` for a template.

- `default_tz`: Default timezone.
- `meetup_groups`: keys mapped to Meetup group URLs.
- `event_config`: (Optional) Custom settings for linking events to specific Discord threads based on title matching.
