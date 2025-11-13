from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse
from fpdf import FPDF
import io
import tempfile
import os
import json
import soundfile as sf
from vosk import Model, KaldiRecognizer

app = FastAPI()

# ------------ Load offline Vosk model ------------
MODEL_PATH = "models/vosk-model-small-en-us-0.15"   # <-- make sure this folder exists
vosk_model = Model(MODEL_PATH)


# ------------ FRONTEND HTML ------------
@app.get("/", response_class=HTMLResponse)
async def index():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Offline Voice → PDF (Vosk)</title>
        <style>
            body { font-family: Arial; text-align:center; padding:40px; }
            button {
                padding: 10px 20px; margin:10px;
                background:#007bff; color:white;
                border:none; border-radius:5px;
                font-size:16px; cursor:pointer;
            }
            button:disabled { background:#aaa; cursor:not-allowed; }
        </style>
    </head>
    <body>

        <h1>🎙️ Offline Audio to PDF using Vosk</h1>
        <p>No internet • No FFmpeg • Windows friendly</p>

        <button id="record">Start Recording</button>
        <button id="stop" disabled>Stop</button>

        <p id="status"></p>

        <!-- Polyfills for WAV recording -->
        <script src="https://unpkg.com/opus-media-recorder/opus-media-recorder.min.js"></script>
        <script src="https://unpkg.com/opus-media-recorder/encoderWorker.min.js"></script>
        <script src="https://unpkg.com/wave-encoder/dist/wave-encoder.min.js"></script>

        <script>
            let mediaRecorder;
            let chunks = [];
            let audioStream;

            const recordBtn = document.getElementById("record");
            const stopBtn = document.getElementById("stop");
            const status = document.getElementById("status");

            recordBtn.onclick = async () => {
                audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });

                mediaRecorder = new MediaRecorder(audioStream, {
                    mimeType: "audio/wav"     // Polyfill forces WAV
                });

                chunks = [];
                mediaRecorder.start();

                recordBtn.disabled = true;
                stopBtn.disabled = false;
                status.textContent = "🎙️ Recording...";

                mediaRecorder.ondataavailable = e => chunks.push(e.data);
            };

            stopBtn.onclick = () => {
                mediaRecorder.stop();
                audioStream.getTracks().forEach(t => t.stop());
                stopBtn.disabled = true;
                status.textContent = "Processing audio... ⏳";

                mediaRecorder.onstop = async () => {
                    const blob = new Blob(chunks, { type: "audio/wav" });
                    const arrayBuffer = await blob.arrayBuffer();

                    // Convert blob → PCM WAV using wave-encoder
                    const wavBuffer = window.waveEncoder.encode({
                        sampleRate: 16000,
                        numChannels: 1,
                        bytesPerSample: 2,
                        samples: new Int16Array(arrayBuffer)
                    });

                    const wavBlob = new Blob([wavBuffer], { type: "audio/wav" });

                    const formData = new FormData();
                    formData.append("file", wavBlob, "audio.wav");

                    const response = await fetch("/audio-to-pdf", {
                        method: "POST",
                        body: formData
                    });

                    const pdfBlob = await response.blob();
                    const pdfUrl = URL.createObjectURL(pdfBlob);

                    const a = document.createElement("a");
                    a.href = pdfUrl;
                    a.download = "transcribed.pdf";
                    a.click();

                    status.textContent = "✅ PDF Downloaded!";
                    recordBtn.disabled = false;
                };
            };
        </script>

    </body>
    </html>
    """


# ------------ API: AUDIO → TEXT → PDF ------------
@app.post("/audio-to-pdf")
async def audio_to_pdf(file: UploadFile = File(...)):

    # Save wav file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    # Load WAV
    audio, samplerate = sf.read(tmp_path)

    # Ensure mono
    if len(audio.shape) == 2:
        audio = audio.mean(axis=1)

    recognizer = KaldiRecognizer(vosk_model, samplerate)
    recognizer.SetWords(True)

    recognizer.AcceptWaveform(audio.tobytes())
    result = json.loads(recognizer.FinalResult())
    text = result.get("text", "").strip()
    print(text)

    os.remove(tmp_path)

    # ----- Create PDF -----
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.multi_cell(0, 10, text if text else "No speech detected.")

    pdf_bytes = io.BytesIO(pdf.output(dest="S").encode("latin1"))
    pdf_bytes.seek(0)

    return StreamingResponse(
        pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=transcribed.pdf"}
    )
