from flask import Flask, render_template

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
    app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
    @app.get('/')
    def dashboard():
        from .common import dashboard_defaults
        return render_template('index.html', defaults=dashboard_defaults())
    return app
