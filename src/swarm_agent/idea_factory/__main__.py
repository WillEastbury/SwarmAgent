"""Entrypoint: python -m swarm_agent.idea_factory"""

from swarm_agent.idea_factory.app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
