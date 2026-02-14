"""Entry point for qman: creates Flask app and runs dev server.

Use config.json for master server (default).
Use config.slave.json for slave server: CONFIG_PATH=config.slave.json python run.py
"""

from app import create_app

# Master: config.json (default). Slave: set CONFIG_PATH=config.slave.json
app = create_app()

if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=app.config.get("PORT", 8436),
        debug=True,
        use_reloader=True,
    )
