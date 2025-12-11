from flask import Flask, render_template, request
from travel_cost_forecasting.src.main import train_and_evaluate_model
from travel_cost_forecasting.src.model import forecast_cost
from travel_cost_forecasting.src.data_processing import ALL_COUNTRIES, COUNTRY_CODES
import calendar
import os
import pickle
import argparse

# Define the path for the cached model
script_dir = os.path.dirname(os.path.abspath(__file__))
model_path = os.path.join(script_dir, 'travel_cost_forecasting', 'models', 'trained_model.pkl')

def create_app(**kwargs):
    app = Flask(__name__, template_folder='travel_cost_forecasting/templates', static_folder='travel_cost_forecasting/static')

    # --- Model Loading and Training ---
    if not os.path.exists(model_path):
        print("No cached model found. Training a new model...")
        models, train_data = train_and_evaluate_model()
        model_data = {
            'models': models,
            'train_data': train_data
        }
        with open(model_path, 'wb') as f:
            pickle.dump(model_data, f)
        print("Model training complete and cached.")

    print(f"Loading model from {model_path}...")
    with open(model_path, 'rb') as f:
        model_data = pickle.load(f)

    app.models = model_data['models']
    app.train_data = model_data['train_data']
    app.model_ready = True
    print("Model loaded successfully.")

    @app.route('/')
    def index():
        month_names = list(calendar.month_name)[1:]
        return render_template('index.html', countries=ALL_COUNTRIES, country_names=COUNTRY_CODES, months=month_names, model_ready=app.model_ready)

    @app.route('/predict', methods=['POST'])
    def predict():
        if not app.model_ready:
            return "Model is not ready yet, please try again in a few moments."

        home_country = request.form['home_country']
        dest_country = request.form['dest_country']
        num_days = int(request.form['num_days'])
        month = int(request.form['month'])
        year = int(request.form['year'])

        total_cost, breakdown, prophet_pred, lstm_pred = forecast_cost(
            app.models,
            app.train_data,
            home_country,
            dest_country,
            num_days,
            month,
            year
        )

        month_names = list(calendar.month_name)[1:]

        # Prepare data for Plotly graphs (can be enhanced)
        graph_data = {
            'prophet_pred': prophet_pred,
            'lstm_pred': lstm_pred,
            'total_pred': total_cost
        }

        return render_template('index.html',
                               countries=ALL_COUNTRIES,
                               country_names=COUNTRY_CODES,
                               months=month_names,
                               prediction=round(total_cost, 2),
                               breakdown=breakdown,
                               graph_data=graph_data,
                               model_ready=app.model_ready)
    return app

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Travel Cost Forecasting Web App')
    parser.add_argument('--retrain', action='store_true', help='Force retraining of the model.')
    args = parser.parse_args()

    if args.retrain and os.path.exists(model_path):
        print(f"Retrain flag set. Deleting cached model at {model_path}...")
        os.remove(model_path)

    app = create_app()
    app.run(debug=True, host='0.0.0.0')
