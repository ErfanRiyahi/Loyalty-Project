from flask import Flask, render_template


# Create the Flask app and register all version 3 components.
def create_app():
    app = Flask(__name__)
    from .routes.scoring import app as scoring
    from .routes.clustering import app as clustering
    from .routes.churn import app as churn

    app.register_blueprint(scoring)
    app.register_blueprint(clustering)
    app.register_blueprint(churn)
    from .routes.monthly import app as monthly

    app.register_blueprint(monthly)
    from .routes.jobs import app as jobs, install

    app.register_blueprint(jobs)
    install(app)
    from .routes.downloads import app as downloads, install as install_downloads

    app.register_blueprint(downloads)
    install_downloads(app)
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

    @app.get("/")
    def dashboard():
        from .common import dashboard_defaults

        return render_template("index.html", defaults=dashboard_defaults())

    return app
