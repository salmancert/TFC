import pandas as pd
from prophet import Prophet
from sklearn.preprocessing import MinMaxScaler
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Input
from sklearn.metrics import mean_squared_error
import numpy as np
from .data_processing import ALL_COUNTRIES
import requests
import re
import json

SEQUENCE_LENGTH = 60

def _get_country_from_ohe(row, prefix):
    """Helper function to find the country code from one-hot encoded columns."""
    for col, value in row.items():
        if col.startswith(prefix) and value == 1:
            return col.split('_', 1)[1]
    return None

def train_prophet_model(data, target_column='y'):
    """
    Trains a Prophet model for a specific target column.
    """
    regressors = [col for col in data.columns if col.startswith('home_') or col.startswith('dest_') or col == 'duration']

    prophet_data = data[['ds', target_column] + regressors].rename(columns={target_column: 'y'})

    model = Prophet()
    for regressor in regressors:
        model.add_regressor(regressor)

    model.fit(prophet_data)
    return model

def create_lstm_model(n_features, sequence_length=SEQUENCE_LENGTH):
    """
    Creates an LSTM model.
    """
    model = Sequential()
    model.add(Input(shape=(sequence_length, n_features)))
    model.add(LSTM(50, return_sequences=True))
    model.add(LSTM(50))
    model.add(Dense(1))
    model.compile(optimizer='adam', loss='mean_squared_error')
    return model

def train_lstm_model(data, target_column='y'):
    """
    Trains an LSTM model for a specific target column.
    """
    if len(data) < SEQUENCE_LENGTH:
        print(f"Warning: Data has {len(data)} rows, but LSTM training requires at least {SEQUENCE_LENGTH}. Skipping LSTM training for {target_column}.")
        return None, None, None

    features = [target_column] + [col for col in data.columns if col.startswith('home_') or col.startswith('dest_') or col == 'duration']
    scaler = MinMaxScaler(feature_range=(0, 1))
    scaled_data = scaler.fit_transform(data[features])

    X, y = [], []
    for i in range(SEQUENCE_LENGTH, len(scaled_data)):
        X.append(scaled_data[i-SEQUENCE_LENGTH:i, :])
        y.append(scaled_data[i, 0])

    X, y = np.array(X), np.array(y)
    if X.shape[0] == 0:
        print(f"Warning: Could not create any sequences for LSTM from data with {len(data)} rows and sequence length {SEQUENCE_LENGTH}. Skipping LSTM training for {target_column}.")
        return None, None, None

    model = create_lstm_model(X.shape[2])
    model.fit(X, y, epochs=50, batch_size=1, verbose=2)

    return model, scaler, scaled_data

def train_hybrid_model(data):
    """
    Trains a hybrid Prophet and LSTM model for each specified target column.
    """
    target_columns = ['y_hotel', 'y_air_ticket', 'y_others']
    models = {}

    for target in target_columns:
        print(f"--- Training model for {target} ---")
        prophet_model = train_prophet_model(data, target_column=target)
        lstm_model, scaler, _ = train_lstm_model(data, target_column=target)

        models[target] = {
            'prophet_model': prophet_model,
            'lstm_model': lstm_model,
            'scaler': scaler
        }

    return models

def evaluate_model(models, train_data, test_data):
    """
    Evaluates the trained models.
    """
    # This function would need to be updated to evaluate each model individually
    # For now, we'll just print a message.
    print("Model evaluation would be performed here.")
    return 0, 0

def _create_future_df(home_country, dest_country, num_days, month, year=2025):
    """
    Creates a future dataframe for prediction.
    """
    future_date = pd.to_datetime(f'{year}-{month}-01')
    future_df = pd.DataFrame({'ds': [future_date], 'duration': [num_days]})

    for country in ALL_COUNTRIES:
        future_df[f'home_{country}'] = 0
        future_df[f'dest_{country}'] = 0

    if f'home_{home_country}' in future_df.columns:
        future_df[f'home_{home_country}'] = 1
    if f'dest_{dest_country}' in future_df.columns:
        future_df[f'dest_{dest_country}'] = 1

    return future_df

def forecast_with_llm(train_data, home_country, dest_country, num_days, month, year):
    """
    Forecasts the travel cost using a local LLM and returns a cost breakdown.
    """
    # 1. Construct the Prompt
    examples = train_data.sample(n=3)
    prompt_examples = ""
    for _, row in examples.iterrows():
        home_country_code = _get_country_from_ohe(row, 'home_')
        dest_country_code = _get_country_from_ohe(row, 'dest_')
        if home_country_code and dest_country_code:
            prompt_examples += (
                f"- Trip from {home_country_code} to {dest_country_code} for {int(row['duration'])} days in month {row['ds'].month}:\n"
                f"  - Air Ticket: €{row['y_air_ticket']:.2f}\n"
                f"  - Accommodation: €{row['y_hotel']:.2f}\n"
                f"  - Others: €{row['y_others']:.2f}\n"
            )

    prompt = (
        "You are a travel cost forecasting expert. Based on the examples below, predict the cost breakdown for the upcoming trip. "
        "Provide your answer *only* in the format 'Category: €Amount'.\n\n"
        "--- Examples ---\n"
        f"{prompt_examples}\n"
        "--- Predict This Trip ---\n"
        f"Trip from {home_country} to {dest_country} for {num_days} days in month {month} of {year}:\n"
        "Your prediction:\n"
    )

    # 2. Call the Local LLM API (Ollama)
    api_url = "http://127.0.0.1:11434/api/generate"
    payload = {
        "model": "llama2",
        "prompt": prompt,
        "stream": False
    }

    try:
        response = requests.post(api_url, json=payload, timeout=20)
        response.raise_for_status()

        response_data = response.json()
        llm_output = response_data.get('response', '')

        # 3. Parse the Response
        air_ticket = float(re.search(r"Air Ticket: €([\d.,]+)", llm_output).group(1).replace(',', ''))
        accommodation = float(re.search(r"Accommodation: €([\d.,]+)", llm_output).group(1).replace(',', ''))
        others = float(re.search(r"Others: €([\d.,]+)", llm_output).group(1).replace(',', ''))

        breakdown = {
            'Air Ticket': air_ticket,
            'Accommodation': accommodation,
            'Others': others
        }
    except requests.exceptions.RequestException as e:
        print(f"🔴 Connection to local LLM failed: {e}")
        breakdown = {'Air Ticket': 0, 'Accommodation': 0, 'Others': 0, 'Error': 'LLM connection failed'}
    except (AttributeError, ValueError) as e:
        print(f"🔴 Failed to parse LLM response: {e}\nResponse was: {llm_output}")
        breakdown = {'Air Ticket': 0, 'Accommodation': 0, 'Others': 0, 'Error': 'LLM parsing failed'}

    return breakdown

def forecast_cost(models, train_data, home_country, dest_country, num_days, month, year, model_choice='hybrid'):
    """
    Forecasts the travel cost for a given trip based on the selected model and returns a cost breakdown.
    """

    if model_choice == 'llm':
        llm_breakdown = forecast_with_llm(train_data, home_country, dest_country, num_days, month, year)
        if 'Error' in llm_breakdown:
            return 0, llm_breakdown, 0, 0

        daily_allowance = 80 * num_days  # Placeholder
        llm_breakdown['Daily Allowance'] = daily_allowance
        total_cost = sum(llm_breakdown.values())
        return total_cost, llm_breakdown, 0, 0

    future_df = _create_future_df(home_country, dest_country, num_days, month, year)

    hybrid_predictions = {}
    for target, model_components in models.items():
        prophet_model = model_components['prophet_model']
        lstm_model = model_components['lstm_model']
        scaler = model_components['scaler']

        prophet_prediction = prophet_model.predict(future_df)['yhat'].values[0]

        if lstm_model and scaler:
            features = [target] + [col for col in train_data.columns if col.startswith('home_') or col.startswith('dest_') or col == 'duration']
            train_features = train_data[features]
            history = train_features.values[-SEQUENCE_LENGTH:]

            future_features = future_df[[col for col in features if col != target]]
            future_features.insert(0, target, 0)
            future_values = future_features[train_features.columns].values

            scaled_history = scaler.transform(history)
            scaled_future = scaler.transform(future_values)
            sequence_to_predict = np.append(scaled_history[1:], scaled_future, axis=0).reshape(1, SEQUENCE_LENGTH, len(features))

            lstm_prediction_scaled = lstm_model.predict(sequence_to_predict, verbose=0)

            dummy_for_inverse = np.zeros((1, len(features)))
            dummy_for_inverse[0, 0] = lstm_prediction_scaled[0,0]
            lstm_prediction = scaler.inverse_transform(dummy_for_inverse)[0,0]

            hybrid_predictions[target] = (prophet_prediction + lstm_prediction) / 2
        else:
            hybrid_predictions[target] = prophet_prediction

    daily_allowance = 80 * num_days # Placeholder value

    breakdown = {
        'Air Ticket': hybrid_predictions.get('y_air_ticket', 0),
        'Accommodation': hybrid_predictions.get('y_hotel', 0),
        'Daily Allowance': daily_allowance,
        'Others': hybrid_predictions.get('y_others', 0)
    }

    if model_choice == 'ensemble':
        llm_breakdown = forecast_with_llm(train_data, home_country, dest_country, num_days, month, year)
        if 'Error' not in llm_breakdown:
            breakdown['Air Ticket'] = (breakdown['Air Ticket'] + llm_breakdown['Air Ticket']) / 2
            breakdown['Accommodation'] = (breakdown['Accommodation'] + llm_breakdown['Accommodation']) / 2
            breakdown['Others'] = (breakdown['Others'] + llm_breakdown['Others']) / 2

    total_cost = sum(breakdown.values())

    return total_cost, breakdown, hybrid_predictions.get('y_air_ticket_prophet', 0), hybrid_predictions.get('y_air_ticket_lstm', 0)
