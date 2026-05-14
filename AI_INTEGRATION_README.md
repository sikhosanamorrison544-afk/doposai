# AI Business Intelligence Integration

This document explains how to set up and use the offline AI business intelligence system for your POS.

## Overview

The AI system uses **Ollama** with the **Phi-2** model to analyze your sales data and provide professional accounting insights. Everything runs **fully offline** on your Raspberry Pi.

## Installation

### Step 1: Install Ollama

Run the installation script:

```bash
cd /home/morrison/Desktop/pos
./install_ollama.sh
```

This script will:
- Install Ollama on your system
- Start the Ollama service
- Download the Phi-2 model (~1.6GB)
- Verify everything is working

**Note:** The download may take several minutes depending on your internet connection.

### Step 2: Verify Installation

Run the test script to verify everything works:

```bash
python3 test_ollama.py
```

You should see:
- ✅ Ollama service is running
- ✅ Phi-2 model is available
- ✅ AI generation is working
- ✅ Performance metrics

### Step 3: Start Your POS System

The AI integration is already built into your POS. Just start the server as usual:

```bash
# Your existing startup command
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Usage

### Accessing AI Insights

1. **Login to your POS system**
2. **Navigate to Admin Panel** (click "Admin" button)
3. **Click the 🤖 AI Insights button** (purple floating icon)
4. **Select analysis period** (7, 14, 30, 60, or 90 days)
5. **Click "🔄 Refresh Analysis"** to generate insights

### What the AI Analyzes

The AI analyzes:
- **Total revenue** for the selected period
- **Number of sales transactions**
- **Top-performing products** (by revenue and quantity)
- **Products with declining sales**
- **Revenue growth** compared to previous period
- **Net profit** (revenue minus expenses/withdrawals)

### AI Output Examples

The AI provides insights like:

> "Your revenue increased by 12% compared to last month. Cooking oil is your top-performing product with 50 units sold generating $500 in revenue. Sugar sales declined by 15% - consider promotional pricing or better shelf placement to boost sales. Overall, your business is performing well with strong growth in essential items."

## Technical Details

### Architecture

```
POS Database (SQLite)
    ↓
Python AI Service (app/ai_service.py)
    ↓
Ollama API (localhost:11434)
    ↓
Phi-2 Model (Offline LLM)
    ↓
AI Analysis Response
    ↓
POS Frontend (Admin Panel)
```

### Files Created

1. **`install_ollama.sh`** - Installation script for Ollama
2. **`app/ai_service.py`** - Python service for AI integration
3. **`test_ollama.py`** - Test script to verify installation
4. **API Endpoints:**
   - `GET /api/ai/analyze?days=30` - Get AI analysis
   - `GET /api/ai/status` - Check Ollama availability

### Database Queries

The AI service queries:
- `sales` table - for transaction data
- `sale_items` table - for product sales details
- `products` table - for product information
- `withdrawals` table - for expense tracking

### Performance

- **Response Time:** 10-30 seconds (depending on Raspberry Pi performance)
- **Memory Usage:** ~2-3GB RAM (Phi-2 model)
- **CPU Usage:** Moderate during analysis
- **Storage:** ~1.6GB for Phi-2 model

## Troubleshooting

### Ollama Not Running

```bash
# Check service status
sudo systemctl status ollama

# Start service
sudo systemctl start ollama

# Enable auto-start on boot
sudo systemctl enable ollama
```

### Model Not Found

```bash
# List installed models
ollama list

# Pull Phi-2 model
ollama pull phi:2.7b
```

### AI Analysis Fails

1. **Check Ollama is running:**
   ```bash
   curl http://localhost:11434/api/tags
   ```

2. **Test model directly:**
   ```bash
   ollama run phi:2.7b "Hello"
   ```

3. **Check POS logs:**
   - Look for errors in the terminal where you started the POS server
   - Check for "Ollama not available" messages

4. **Verify database has sales data:**
   - Make sure you have sales transactions in your database
   - The AI needs data to analyze

### Slow Performance

On Raspberry Pi, AI analysis may take 20-30 seconds. This is normal. The system is optimized for:
- **Raspberry Pi 5** with 16GB RAM
- **Offline operation** (no internet required after setup)
- **Low resource usage** when not analyzing

## API Usage Examples

### Get AI Analysis (Python)

```python
import requests

token = "your_auth_token"
response = requests.get(
    "http://localhost:8000/api/ai/analyze?days=30",
    headers={"Authorization": f"Bearer {token}"}
)
data = response.json()
print(data["ai_insights"])
```

### Check AI Status (Python)

```python
import requests

token = "your_auth_token"
response = requests.get(
    "http://localhost:8000/api/ai/status",
    headers={"Authorization": f"Bearer {token}"}
)
status = response.json()
print(f"Ollama available: {status['ollama_available']}")
```

## Customization

### Change AI Model

Edit `app/ai_service.py`:

```python
OLLAMA_MODEL = "phi:2.7b"  # Change to another model
```

Then pull the new model:
```bash
ollama pull your-model-name
```

### Adjust AI Prompt

Edit the `_build_analysis_prompt()` method in `app/ai_service.py` to customize the AI's analysis style.

### Change Analysis Period

The frontend allows selecting 7, 14, 30, 60, or 90 days. To add more options, edit `templates/admin.html` and add more `<option>` tags to the `ai-period-select` dropdown.

## Security Notes

- The AI runs **completely offline** - no data leaves your system
- All analysis is done locally on your Raspberry Pi
- No internet connection required after initial model download
- All data stays in your local database

## Support

If you encounter issues:

1. Run `python3 test_ollama.py` to diagnose problems
2. Check Ollama service: `sudo systemctl status ollama`
3. Review POS server logs for error messages
4. Verify you have sales data in your database

## Next Steps

After installation:
1. ✅ Run `./install_ollama.sh`
2. ✅ Run `python3 test_ollama.py` to verify
3. ✅ Start your POS server
4. ✅ Test AI insights in Admin panel
5. ✅ Enjoy professional business analysis!

---

**Note:** This AI system is designed for **internal business analysis only**. It is NOT a customer-facing chatbot. All insights are for shop owner decision-making.

