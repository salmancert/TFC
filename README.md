# Travel Cost Forecasting

This project forecasts travel costs using a hybrid model of Prophet and LSTM. It provides a web interface for users to get cost estimates.

## Setup

1.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Place your data:**
    -   `travel_data.csv`: Your historical travel expense data.
    -   `daily_allowance_rates.xlsx`: The daily allowance rates.

    Both files should be placed in the `travel_cost_forecasting/data/` directory.

## Running the Application

1.  **Start the Flask server:**
    ```bash
    python app.py
    ```

2.  **Force retraining (optional):**
    If you have updated the data and want to force the model to retrain, use the `--retrain` flag:
    ```bash
    python app.py --retrain
    ```

3.  **Access the application:**
    Open your web browser and go to `http://127.0.0.1:5000`.
