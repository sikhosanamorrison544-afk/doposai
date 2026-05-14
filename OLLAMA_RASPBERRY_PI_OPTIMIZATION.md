# Ollama + Phi-2 Optimization for Raspberry Pi 5
## Ultra-Fast Configuration for POS Real-Time Usage

### Goal
- **Response time: <2 seconds**
- **Minimal CPU/RAM usage**
- **Short, factual responses (max 5 lines)**
- **Suitable for real-time POS interactions**

---

## 1. Ollama Runtime Configuration

### Start Ollama with Optimized Flags

Create a systemd service or startup script with these flags:

```bash
# Recommended Ollama startup command for Raspberry Pi 5
OLLAMA_NUM_PARALLEL=1 \
OLLAMA_MAX_LOADED_MODELS=1 \
OLLAMA_NUM_THREAD=4 \
OLLAMA_FLASH_ATTENTION=0 \
ollama serve
```

### Environment Variables (Add to `/etc/environment` or `~/.bashrc`)

```bash
# Limit concurrent requests (Pi 5 has limited resources)
export OLLAMA_NUM_PARALLEL=1

# Only keep one model loaded at a time
export OLLAMA_MAX_LOADED_MODELS=1

# Use 4 CPU threads (Pi 5 has 4 cores)
export OLLAMA_NUM_THREAD=4

# Disable flash attention (not available on ARM)
export OLLAMA_FLASH_ATTENTION=0

# Reduce memory usage
export OLLAMA_KEEP_ALIVE=5m
```

### Systemd Service (Recommended)

Create `/etc/systemd/system/ollama-optimized.service`:

```ini
[Unit]
Description=Ollama AI Service (Optimized for Raspberry Pi 5)
After=network.target

[Service]
Type=simple
User=ollama
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_NUM_THREAD=4"
Environment="OLLAMA_FLASH_ATTENTION=0"
Environment="OLLAMA_KEEP_ALIVE=5m"
ExecStart=/usr/local/bin/ollama serve
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable ollama-optimized
sudo systemctl start ollama-optimized
```

---

## 2. Phi-2 Model Configuration

### Pull Phi-2 Model (if not already installed)

```bash
ollama pull phi:2.7b
```

### Create Custom Modelfile (Optional - for even faster responses)

Create `~/.ollama/modelfiles/phi-fast`:

```dockerfile
FROM phi:2.7b

# Set system prompt for rule-based accounting responses
SYSTEM """You are a fast accounting rule engine. Give factual, short answers (max 5 lines). No explanations."""

# Template for ultra-fast responses
TEMPLATE """{{ .System }}

Data: {{ .Prompt }}

Answer (max 5 lines):"""
```

Then create the model:
```bash
ollama create phi-fast -f ~/.ollama/modelfiles/phi-fast
```

Update `app/ai_service.py` to use `phi-fast` instead of `phi:2.7b` if you create this custom model.

---

## 3. Python Integration (Already Implemented)

The POS system is already configured with these optimizations in `app/ai_service.py`:

### Chat Configuration
- **Temperature**: 0.0 (deterministic, fastest)
- **Top P**: 0.3 (minimal search space)
- **Top K**: 10 (minimal vocabulary search)
- **Num Predict**: 25 tokens (max 5 lines)
- **Context Window**: 512 (reduced from 2048)
- **Threads**: 4 (Pi 5 CPU cores)
- **Timeout**: 3 seconds

### Analysis Configuration
- **Temperature**: 0.0
- **Num Predict**: 50 tokens
- **Timeout**: 5 seconds

---

## 4. Raspberry Pi 5 System Optimizations

### CPU Governor (Set to Performance Mode)

```bash
# Check current governor
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor

# Set to performance mode (faster, but higher power usage)
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor

# Make permanent (add to /etc/rc.local or systemd service)
echo 'echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor' | sudo tee -a /etc/rc.local
```

### Memory/Swap Optimization

```bash
# Increase swap for model loading (if needed)
sudo dphys-swapfile swapoff
sudo nano /etc/dphys-swapfile
# Set CONF_SWAPSIZE=2048 (2GB)
sudo dphys-swapfile setup
sudo dphys-swapfile swapon
```

### Disable Unnecessary Services

```bash
# Disable services you don't need (free up CPU/RAM)
sudo systemctl disable bluetooth
sudo systemctl disable avahi-daemon
sudo systemctl disable cups
```

---

## 5. Testing & Verification

### Test Response Time

```bash
# Test Ollama directly
time curl http://localhost:11434/api/generate -d '{
  "model": "phi:2.7b",
  "prompt": "Data: $1000 rev, $800 profit. Advice:",
  "stream": false,
  "options": {
    "temperature": 0.0,
    "num_predict": 25,
    "num_ctx": 512
  }
}'
```

**Expected**: Response time <2 seconds

### Monitor Resource Usage

```bash
# Monitor CPU and RAM while testing
htop

# Or use top
top -p $(pgrep ollama)
```

---

## 6. Troubleshooting

### If responses are still slow:

1. **Check Ollama is using optimized settings**:
   ```bash
   ps aux | grep ollama
   # Should show environment variables set
   ```

2. **Verify model is loaded**:
   ```bash
   ollama list
   # phi:2.7b should show as loaded
   ```

3. **Check system load**:
   ```bash
   uptime
   # Load average should be <2.0 for Pi 5
   ```

4. **Reduce other processes**:
   - Close unnecessary browser tabs
   - Stop other services
   - Check for background tasks

### If you get timeout errors:

1. **Increase timeout slightly** (in `app/ai_service.py`):
   ```python
   OLLAMA_CHAT_TIMEOUT = 4  # Increase from 3 to 4 seconds
   ```

2. **Check Ollama logs**:
   ```bash
   journalctl -u ollama-optimized -f
   ```

---

## 7. Performance Benchmarks

### Expected Performance on Raspberry Pi 5 (16GB RAM):

- **First request (cold start)**: 3-5 seconds (model loading)
- **Subsequent requests (warm)**: 1-2 seconds
- **CPU usage**: 60-80% during generation
- **RAM usage**: ~2-3GB for Phi-2 model
- **Response length**: 20-50 words (max 5 lines)

---

## 8. Production Deployment Checklist

- [ ] Ollama service configured with optimized environment variables
- [ ] Systemd service created and enabled
- [ ] CPU governor set to performance mode
- [ ] Unnecessary services disabled
- [ ] Swap configured (if needed)
- [ ] Model tested and verified (<2s response time)
- [ ] POS system using optimized AI service settings
- [ ] Monitoring in place (logs, resource usage)

---

## Summary

This configuration transforms Ollama + Phi-2 into a **fast accounting rule engine** suitable for real-time POS usage on Raspberry Pi 5. The key optimizations are:

1. **Minimal token generation** (25 tokens = ~5 lines)
2. **Zero temperature** (deterministic, fastest)
3. **Reduced context window** (512 vs 2048)
4. **Single-threaded requests** (no parallel processing)
5. **Short timeouts** (3-5 seconds max)
6. **System-level optimizations** (CPU governor, disabled services)

**Result**: Sub-2-second responses for real-time business insights in your POS system.

