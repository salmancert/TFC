from flask import Flask, render_template, request
from travel_cost_forecasting.src.main import train_and_evaluate_model
from travel_cost_forecasting.src.model import forecast_cost
from travel_cost_forecasting.src.data_processing import ALL_COUNTRIES
import calendar
import threading
import pickle
import os

def create_app():
    app = Flask(__name__)

    # --- Model Loading and Training ---
    app.model_ready = False

    # Define the path for the cached model
    script_dir = os.path.dirname(os.path.abspath(__file__))
    model_path = os.path.join(script_dir, 'models', 'trained_model.pkl')

    def load_or_train_model():
        """Loads a pre-trained model or trains a new one."""
        if os.path.exists(model_path):
            print(f"Loading cached model from {model_path}...")
            with open(model_path, 'rb') as f:
                model_data = pickle.load(f)
            app.prophet_model = model_data['prophet_model']
            app.lstm_model = model_data['lstm_model']
            app.scaler = model_data['scaler']
            app.train_data = model_data['train_data']
            app.model_ready = True
            print("Cached model loaded successfully.")
        else:
            print("No cached model found. Starting background training...")
            # If no cached model, train in the background
            threading.Thread(target=train_model_and_cache).start()

    def train_model_and_cache():
        """Trains the model and caches it."""
        print("Training model in background...")
        # Note: train_and_evaluate_model now saves the model itself
        prophet_model, lstm_model, scaler, train_data = train_and_evaluate_model()
        app.prophet_model = prophet_model
        app.lstm_model = lstm_model
        app.scaler = scaler
        app.train_data = train_data
        app.model_ready = True
        print("Model training complete and cached.")

    # Load or start training the model when the app starts
    load_or_train_model()
    # --- End Model Loading ---

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
