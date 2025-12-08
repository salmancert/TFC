from flask import Flask, render_template, request
from travel_cost_forecasting.src.main import train_and_evaluate_model
from travel_cost_forecasting.src.model import forecast_cost
from travel_cost_forecasting.src.data_processing import ALL_COUNTRIES
import calendar
import threading

def create_app():
    app = Flask(__name__)

    # Global variables to hold the trained model and track its status
    app.model_ready = False
    app.prophet_model = None
    app.lstm_model = None
    app.scaler = None
    app.train_data = None

    def train_model_thread():
        """Function to train the model in a separate thread."""
        print("Training model in background...")
        app.prophet_model, app.lstm_model, app.scaler, app.train_data = train_and_evaluate_model()
        app.model_ready = True
        print("Model training complete.")

    # Start training the model in a background thread when the app starts
    threading.Thread(target=train_model_thread).start()

    @app.route('/')
    def index():
        month_names = list(calendar.month_name)[1:]
        return render_template('index.html', countries=ALL_COUNTRIES, months=month_names, model_ready=app.model_ready)

    @app.route('/predict', methods=['POST'])
    def predict():
        if not app.model_ready:
            return "Model is not ready yet, please try again in a few moments."

        home_country = request.form['home_country']
        dest_country = request.form['dest_country']
        num_days = int(request.form['num_days'])
        month = int(request.form['month'])
        year = int(request.form['year'])

        cost = forecast_cost(
            app.prophet_model,
            app.lstm_model,
            app.scaler,
            app.train_data,
            home_country,
            dest_country,
            num_days,
            month,
            year
        )

        month_names = list(calendar.month_name)[1:]
        return render_template('index.html', countries=ALL_COUNTRIES, months=month_names, prediction=cost, model_ready=app.model_ready)

    return app

app = create_app()
