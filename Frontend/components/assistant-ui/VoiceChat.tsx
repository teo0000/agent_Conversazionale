"use client";
import React, { useRef, useState } from "react";
import { removeDuplicatePhrases, cleanTextForTTS } from "../../lib/text-utils";

const VoiceChat: React.FC<{
    recording: boolean;
    onStart: () => void;
    onStop: () => void;
    responseText: string | null;
    setResponseText: (text: string | null) => void;
    addErrorMessage?: (text: string) => void;
    onAudioSendToBackend?: () => void;
    onProcessTranscribedText: (text: string) => void;
}> = ({ recording, onStart, onStop, responseText, setResponseText, addErrorMessage, onAudioSendToBackend, onProcessTranscribedText }) => {
    const autoStopTimerRef = useRef<NodeJS.Timeout | null>(null);
    const processingStopRef = useRef(false);
    const [audioUrl, setAudioUrl] = useState<string | null>(null);
    const [processingAudio, setProcessingAudio] = useState(false);
    const mediaRecorderRef = useRef<MediaRecorder | null>(null);
    const audioChunks = useRef<Blob[]>([]);
    const speechRecognitionRef = useRef<any>(null);

    // Avvia la registrazione
    const startRecording = async () => {
        console.log("VoiceChat: Attempting to start recording...");
        setAudioUrl(null);
        processingStopRef.current = false; // Resetta il flag per una nuova registrazione
        audioChunks.current = []; // Assicurati che i chunk siano resettati
        // Pulisci qualsiasi timer precedente prima di impostarne uno nuovo
        if (autoStopTimerRef.current) {
            clearTimeout(autoStopTimerRef.current);
            autoStopTimerRef.current = null;
        }
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            console.log("VoiceChat: Microphone access granted.");
            const mediaRecorder = new MediaRecorder(stream);
            mediaRecorderRef.current = mediaRecorder;
            audioChunks.current = [];

            // --- INTEGRAZIONE SPEECH RECOGNITION ---
            const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
            if (SpeechRecognition) {
                const recognition = new SpeechRecognition();
                recognition.continuous = false;
                recognition.interimResults = false;
                recognition.lang = 'it-IT';
                recognition.onstart = () => {
                    console.log('SpeechRecognition: started');
                };
                recognition.onspeechend = () => {
                    console.log('SpeechRecognition: speech ended, stopping MediaRecorder');
                    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
                        mediaRecorderRef.current.stop();
                    }
                    recognition.stop();
                };
                recognition.onend = () => {
                    console.log('SpeechRecognition: ended');
                };
                recognition.onerror = (event: any) => {
                    console.warn('SpeechRecognition: error', event);
                };
                speechRecognitionRef.current = recognition;
                recognition.start();
            } else {
                console.warn('SpeechRecognition API non supportata su questo browser.');
            }
            // --- FINE INTEGRAZIONE SPEECH RECOGNITION ---

            mediaRecorder.onstart = () => {
                console.log("VoiceChat: MediaRecorder started.");
                onStart();
            };

            mediaRecorder.ondataavailable = (event) => {
                console.log("VoiceChat: MediaRecorder data available, chunk size:", event.data.size);
                if (event.data.size > 0) {
                    audioChunks.current.push(event.data);
                }
            };

            mediaRecorder.onstop = async () => {
                if (processingStopRef.current) {
                    console.log("VoiceChat: Already processing stop, skipping duplicate call to onstop logic.");
                    return;
                }
                processingStopRef.current = true;
                // Pulisci il timer di auto-stop se onstop è stato triggerato prima
                if (autoStopTimerRef.current) {
                    clearTimeout(autoStopTimerRef.current);
                    autoStopTimerRef.current = null;
                }
                try {
                    console.log("VoiceChat: MediaRecorder stopped. Processing audio chunks:", audioChunks.current.length);
                    if (audioChunks.current.length === 0) {
                        console.warn("VoiceChat: No audio chunks recorded.");
                        setResponseText("Nessun audio registrato. Riprova.");
                        if (addErrorMessage) addErrorMessage("Nessun audio registrato. Riprova.");
                        return;
                    }
                    const audioBlob = new Blob(audioChunks.current, { type: "audio/webm" });
                    console.log("VoiceChat: Audio blob created, size:", audioBlob.size, "type:", audioBlob.type);
                    // Invia l'audio al backend per trascrizione
                    const formData = new FormData();
                    formData.append("file", audioBlob, "audio.webm");
                    try {
                        console.log("VoiceChat: Sending audio to backend for transcription...");
                        if (onAudioSendToBackend) onAudioSendToBackend();
                        setProcessingAudio(true);
                        const res = await fetch("http://localhost:8000/agent/audio", {
                            method: "POST",
                            body: formData,
                        });
                        console.log("VoiceChat: Transcription response status:", res.status);
                        if (res.ok) {
                            const data = await res.json();
                            console.log("VoiceChat: Transcription response data:", data);
                            setAudioUrl(null);
                            let cleanText = data.transcribed_text || "";
                            cleanText = removeDuplicatePhrases(cleanText);
                            cleanText = cleanTextForTTS(cleanText); // Applica la pulizia
                            console.log("VoiceChat: Testo pulito inviato:", cleanText);
                            setResponseText(cleanText);
                            if (cleanText.trim() && onProcessTranscribedText) {
                                onProcessTranscribedText(cleanText);
                            }
                        } else {
                            const errText = await res.text();
                            console.error("VoiceChat: Transcription API request failed.", errText);
                            let errorMsg = "Errore dal backend";
                            try {
                                errorMsg = JSON.parse(errText).error || errorMsg;
                            } catch { }
                            setResponseText(errorMsg);
                            if (addErrorMessage) {
                                addErrorMessage(errorMsg);
                            }
                        }
                    } catch (err) {
                        console.error("VoiceChat: Error during fetch operation:", err);
                        setResponseText("Errore di rete durante la trascrizione.");
                        if (addErrorMessage) {
                            addErrorMessage("Errore di rete durante la trascrizione.");
                        }
                    }
                } finally {
                    onStop(); // Chiama la prop onStop per aggiornare lo stato nel genitore
                    processingStopRef.current = false; // Resetta il flag per la prossima registrazione
                }
            };

            mediaRecorder.start();

            // Stop automatico dopo 30 secondi
            autoStopTimerRef.current = setTimeout(() => {
                if (mediaRecorderRef.current && mediaRecorderRef.current.state === "recording") {
                    console.log("VoiceChat: Auto-stopping after 30 seconds");
                    mediaRecorderRef.current.stop();
                }
            }, 30000);
        } catch (err) {
            console.error("VoiceChat: Error starting recording (getUserMedia or MediaRecorder setup):", err);
            setResponseText("Errore nell'accesso al microfono o nella registrazione.");
            if (addErrorMessage) addErrorMessage("Errore nell'accesso al microfono o nella registrazione.");
            onStop();
        }
    };

    // Ferma la registrazione
    const stopRecording = () => {
        // Pulisci il timer di auto-stop, dato che stiamo fermando manualmente
        if (autoStopTimerRef.current) {
            clearTimeout(autoStopTimerRef.current);
            autoStopTimerRef.current = null;
        }
        if (mediaRecorderRef.current && mediaRecorderRef.current.state === "recording") {
            console.log("VoiceChat: Attempting to stop recording. Current state:", mediaRecorderRef.current.state);
            mediaRecorderRef.current.stop();
        } else {
            console.log("VoiceChat: Attempted to stop recording, but state was not 'recording'.");
        }
        // Ferma anche lo SpeechRecognition se ancora attivo
        if (speechRecognitionRef.current) {
            try { speechRecognitionRef.current.stop(); } catch { }
            speechRecognitionRef.current = null;
        }
    };

    // --- GESTIONE LOADER ELABORAZIONE AUDIO ---
    // Attiva loader quando si invia audio al backend
    React.useEffect(() => {
        if (!recording && processingAudio) {
            // Se non stiamo più registrando e il loader è attivo, resetta dopo ricezione testo
            if (responseText) setProcessingAudio(false);
        }
    }, [recording, responseText]);

    React.useEffect(() => {
        console.log("VoiceChat: useEffect triggered. recording prop:", recording);
        if (recording) {
            startRecording();
        } else {
            stopRecording();
        }
        // Funzione di cleanup
        return () => {
            if (autoStopTimerRef.current) {
                clearTimeout(autoStopTimerRef.current);
                autoStopTimerRef.current = null;
            }
            if (mediaRecorderRef.current && mediaRecorderRef.current.state === "recording") {
                mediaRecorderRef.current.stop();
            }
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [recording]);

    // NON renderizzare nulla!
    return (
        <>
            {processingAudio && !responseText && (
                <div className="flex justify-start w-full items-center gap-3 mt-2 mb-1">
                    <div className="bg-white/90 dark:bg-zinc-900/80 shadow-lg rounded-full p-2 flex flex-col items-center animate-fade-in-up transition-all duration-700 min-w-[56px] min-h-[56px] max-w-[56px] max-h-[56px] justify-center">
                        <div className="bg-blue-100 dark:bg-blue-900 rounded-full p-1 relative flex items-center justify-center w-8 h-8">
                            <svg className="animate-spin" width="16" height="16" viewBox="0 0 24 24">
                                <circle className="opacity-20" cx="12" cy="12" r="7" stroke="#2563eb" strokeWidth="3" fill="none" />
                                <path className="opacity-80" fill="#2563eb" d="M4 12a8 8 0 018-8v2z" />
                            </svg>
                        </div>
                    </div>
                    <span className="text-sm font-medium text-blue-700 dark:text-blue-300 animate-pulse ml-1">Sto trascrivendo l'audio...</span>
                </div>
            )}
        </>
    );
};

export default VoiceChat;