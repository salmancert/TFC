import pandas as pd
from prophet import Prophet
from sklearn.preprocessing import MinMaxScaler
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense
from sklearn.metrics import mean_squared_error
import numpy as np
from travel_cost_forecasting.src.data_processing import ALL_COUNTRIES

SEQUENCE_LENGTH = 60

def train_prophet_model(data):
    """
    Trains a Prophet model.

    Args:
        data (pandas.DataFrame): The preprocessed data.

    Returns:
        prophet.Prophet: The trained Prophet model.
    """

    regressors = [col for col in data.columns if col.startswith('home_') or col.startswith('dest_') or col == 'duration']

    model = Prophet()
    for regressor in regressors:
        model.add_regressor(regressor)

    model.fit(data)
    return model

def create_lstm_model(n_features, sequence_length=SEQUENCE_LENGTH):
    """
    Creates an LSTM model.
    """
    model = Sequential()
    model.add(LSTM(50, return_sequences=True, input_shape=(sequence_length, n_features)))
    model.add(LSTM(50))
    model.add(Dense(1))
    model.compile(optimizer='adam', loss='mean_squared_error')
    return model

def train_lstm_model(data):
    """
    Trains an LSTM model.

    Args:
        data (pandas.DataFrame): The preprocessed data.

    Returns:
        tuple: A tuple containing the trained LSTM model, the scaler, and the scaled data. Returns (None, None, None) if data is insufficient.
    """
    if len(data) < SEQUENCE_LENGTH:
        print(f"Warning: Data has {len(data)} rows, but LSTM training requires at least {SEQUENCE_LENGTH}. Skipping LSTM training.")
        return None, None, None

    features = ['y'] + [col for col in data.columns if col.startswith('home_') or col.startswith('dest_') or col == 'duration']
    scaler = MinMaxScaler(feature_range=(0, 1))
    scaled_data = scaler.fit_transform(data[features])

    X, y = [], []
    for i in range(SEQUENCE_LENGTH, len(scaled_data)):
        X.append(scaled_data[i-SEQUENCE_LENGTH:i, :])
        y.append(scaled_data[i, 0])

    X, y = np.array(X), np.array(y)
    if X.shape[0] == 0:
        print(f"Warning: Could not create any sequences for LSTM from data with {len(data)} rows and sequence length {SEQUENCE_LENGTH}. Skipping LSTM training.")
        return None, None, None

    model = create_lstm_model(X.shape[2])
    model.fit(X, y, epochs=50, batch_size=1, verbose=2)

    return model, scaler, scaled_data

def train_hybrid_model(data):
    """
    Trains a hybrid Prophet and LSTM model.

    Args:
        data (pandas.DataFrame): The preprocessed data.

    Returns:
        tuple: A tuple containing the trained Prophet model, the trained LSTM model, the scaler, and the scaled data.
    """
    prophet_model = train_prophet_model(data)
    lstm_model, scaler, scaled_data = train_lstm_model(data)

    return prophet_model, lstm_model, scaler, scaled_data

def evaluate_model(prophet_model, lstm_model, scaler, train_data, test_data):
    """
    Evaluates the hybrid model.
    """
    regressors = [col for col in test_data.columns if col.startswith('home_') or col.startswith('dest_') or col == 'duration']
    prophet_predictions = prophet_model.predict(test_data[['ds'] + regressors])['yhat'].values
    y_true = test_data['y'].values

    if lstm_model is None:
        print("Evaluating Prophet model only.")
        rmse = np.sqrt(mean_squared_error(y_true, prophet_predictions))
        mse = mean_squared_error(y_true, prophet_predictions)
        return rmse, mse

    features = ['y'] + [col for col in train_data.columns if col.startswith('home_') or col.startswith('dest_') or col == 'duration']

    # Combine train and test data for creating sequences
    full_data_scaled = scaler.transform(pd.concat([train_data[features], test_data[features]]))

    X_test, y_test = [], []
    for i in range(len(train_data), len(full_data_scaled)):
        X_test.append(full_data_scaled[i-SEQUENCE_LENGTH:i, :])
        y_test.append(full_data_scaled[i, 0])

    X_test, y_test = np.array(X_test), np.array(y_test)

    lstm_predictions_scaled = lstm_model.predict(X_test, verbose=0)

    dummy_for_inverse = np.zeros((len(lstm_predictions_scaled), len(features)))
    dummy_for_inverse[:, 0] = lstm_predictions_scaled.flatten()
    lstm_predictions = scaler.inverse_transform(dummy_for_inverse)[:, 0]

    min_len = min(len(prophet_predictions), len(lstm_predictions))
    prophet_predictions = prophet_predictions[:min_len]
    lstm_predictions = lstm_predictions[:min_len]
    y_true = y_true[:min_len]

    hybrid_predictions = (prophet_predictions + lstm_predictions) / 2
    rmse = np.sqrt(mean_squared_error(y_true, hybrid_predictions))
    mse = mean_squared_error(y_true, hybrid_predictions)

    return rmse, mse

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

def forecast_cost(prophet_model, lstm_model, scaler, train_data, home_country, dest_country, num_days, month, year):
    """
    Forecasts the travel cost for a given trip.
    """
    future_df = _create_future_df(home_country, dest_country, num_days, month, year)

    prophet_prediction = prophet_model.predict(future_df)['yhat'].values[0]

    if lstm_model is None:
        return prophet_prediction

    features = ['y'] + [col for col in train_data.columns if col.startswith('home_') or col.startswith('dest_') or col == 'duration']
    train_features = train_data[features]

    history = train_features.values[-SEQUENCE_LENGTH:]

    future_features = future_df[features[1:]]
    future_features.insert(0, 'y', 0)
    future_values = future_features[train_features.columns].values

    scaled_history = scaler.transform(history)
    scaled_future = scaler.transform(future_values)

    sequence_to_predict = np.append(scaled_history[1:], scaled_future, axis=0).reshape(1, SEQUENCE_LENGTH, len(features))

    lstm_prediction_scaled = lstm_model.predict(sequence_to_predict, verbose=0)

    dummy_for_inverse = np.zeros((1, len(features)))
    dummy_for_inverse[0, 0] = lstm_prediction_scaled[0,0]
    lstm_prediction = scaler.inverse_transform(dummy_for_inverse)[0,0]

    hybrid_prediction = (prophet_prediction + lstm_prediction) / 2

    return hybrid_prediction
