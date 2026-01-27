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
    """Loads data, trains the models, evaluates them, and saves the trained models."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(script_dir, '..', 'data')
    models_dir = os.path.join(script_dir, '..', 'models')
    os.makedirs(models_dir, exist_ok=True)

    travel_data_path = os.path.join(data_dir, 'travel_data.csv')
    daily_allowance_path = os.path.join(data_dir, 'daily_allowance.xlsx')
    model_path = os.path.join(models_dir, 'trained_model.pkl')

    travel_data = load_travel_data(travel_data_path)
    daily_allowance_data = load_daily_allowance(daily_allowance_path)

    data = preprocess_data(travel_data, daily_allowance_data)

    train_data, test_data = train_test_split(data, test_size=0.2, shuffle=False)

    # Train a hybrid model for each cost category
    models = train_hybrid_model(train_data)

    if not test_data.empty:
        rmse, mse = evaluate_model(models, train_data, test_data)
        # print(f'Overall RMSE: {rmse}')
        # print(f'Overall MSE: {mse}')
    else:
        print("Test data is empty, skipping evaluation.")

    # Save the trained models and training data to a file
    with open(model_path, 'wb') as f:
        pickle.dump({
            'models': models,
            'train_data': train_data
        }, f)
    print(f"Models saved to {model_path}")

    return models, train_data

def main():
    """
    Main function to run the travel cost forecasting model from the command line.
    """
    args = parse_arguments()
    models, train_data = train_and_evaluate_model()

    if args.home_country and args.dest_country and args.num_days and args.month:
        total_cost, breakdown, _, _ = forecast_cost(
            models,
            train_data,
            args.home_country,
            args.dest_country,
            args.num_days,
            args.month,
            args.year
        )
        print(f'Forecasted Total Cost: {total_cost}')
        print('Cost Breakdown:')
        for category, cost in breakdown.items():
            print(f'  {category}: {cost}')

if __name__ == '__main__':
    main()
