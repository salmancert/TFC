from .data_processing import load_travel_data, load_daily_allowance, preprocess_data
from .model import train_hybrid_model, evaluate_model, forecast_cost
from sklearn.model_selection import train_test_split
import argparse
import os
import pickle

def parse_arguments():
    """Parses command-line arguments for forecasting."""
    parser = argparse.ArgumentParser(description='Travel Cost Forecasting')
    parser.add_argument('--home_country', type=str, help='Home country code (e.g., US)')
    parser.add_argument('--dest_country', type=str, help='Destination country code (e.g., CN)')
    parser.add_argument('--num_days', type=int, help='Number of days for the trip')
    parser.add_argument('--month', type=int, help='Month of the trip (1-12)')
    parser.add_argument('--year', type=int, default=2025, help='Year of the trip')
    return parser.parse_args()

def train_and_evaluate_model():
    """Loads data, trains the model, evaluates it, and saves the trained model."""
    # Get the absolute path to the data and model files
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(script_dir, '..', 'data')
    models_dir = os.path.join(script_dir, '..', 'models')
    os.makedirs(models_dir, exist_ok=True) # Ensure models directory exists

    travel_data_path = os.path.join(data_dir, 'travel_data.csv')
    daily_allowance_path = os.path.join(data_dir, 'daily_allowance.xlsx')
    model_path = os.path.join(models_dir, 'trained_model.pkl')

    # Load data
    travel_data = load_travel_data(travel_data_path)
    daily_allowance_data = load_daily_allowance(daily_allowance_path)

    # Preprocess data
    data = preprocess_data(travel_data, daily_allowance_data)

    # Split data into training and testing sets
    train_data, test_data = train_test_split(data, test_size=0.2, shuffle=False)

    # Train hybrid model
    prophet_model, lstm_model, scaler, _ = train_hybrid_model(train_data)

    # Evaluate model
    if not test_data.empty:
        rmse, mse = evaluate_model(prophet_model, lstm_model, scaler, train_data, test_data)
        print(f'RMSE: {rmse}')
        print(f'MSE: {mse}')
    else:
        print("Test data is empty, skipping evaluation.")

    # Save the trained model objects to a file
    with open(model_path, 'wb') as f:
        pickle.dump({
            'prophet_model': prophet_model,
            'lstm_model': lstm_model,
            'scaler': scaler,
            'train_data': train_data
        }, f)
    print(f"Model saved to {model_path}")

    return prophet_model, lstm_model, scaler, train_data

def main():
    """
    Main function to run the travel cost forecasting model from the command line.
    """
    args = parse_arguments()
    prophet_model, lstm_model, scaler, train_data = train_and_evaluate_model()

    # Forecast cost
    if args.home_country and args.dest_country and args.num_days and args.month:
        cost = forecast_cost(prophet_model, lstm_model, scaler, train_data, args.home_country, args.dest_country, args.num_days, args.month, args.year)
        print(f'Forecasted cost: {cost}')

if __name__ == '__main__':
    main()
