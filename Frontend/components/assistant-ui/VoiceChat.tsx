"use client";
import React, { useRef, useState } from "react";

const VoiceChat: React.FC<{
    recording: boolean;
    onStart: () => void;
    onStop: () => void;
    responseText: string | null;
    setResponseText: (text: string) => void;
    addUserMessage?: (text: string) => void;
    addAssistantMessage?: (text: string) => void;
    addErrorMessage?: (text: string) => void;
    lastSentVoiceText?: string | null;
    setLastSentVoiceText?: (text: string) => void;
}> = ({ recording, onStart, onStop, responseText, setResponseText, addUserMessage, addAssistantMessage, addErrorMessage, lastSentVoiceText, setLastSentVoiceText }) => {
    const autoStopTimerRef = useRef<NodeJS.Timeout | null>(null);
    const processingStopRef = useRef(false);
    const [audioUrl, setAudioUrl] = useState<string | null>(null);
    const mediaRecorderRef = useRef<MediaRecorder | null>(null);
    const audioChunks = useRef<Blob[]>([]);

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
                        const res = await fetch("http://localhost:8000/agent/audio", {
                            method: "POST",
                            body: formData,
                        });
                        console.log("VoiceChat: Transcription response status:", res.status);
                        if (res.ok) {
                            const data = await res.json();
                            console.log("VoiceChat: Transcription response data:", data);
                            setAudioUrl(null);
                            function removeDuplicatePhrases(text: string): string {
                                const words = text.trim().split(/\s+/);
                                const n = words.length;
                                for (let len = Math.floor(n / 2); len >= 2; len--) {
                                    for (let start = 0; start <= n - 2 * len; start++) {
                                        const seq1 = words.slice(start, start + len).join(" ");
                                        const seq2 = words.slice(start + len, start + 2 * len).join(" ");
                                        if (seq1 === seq2) {
                                            return [
                                                ...words.slice(0, start + len),
                                                ...words.slice(start + 2 * len)
                                            ].join(" ");
                                        }
                                    }
                                }
                                return text;
                            }
                            let cleanText = data.transcribed_text || "";
                            cleanText = removeDuplicatePhrases(cleanText);
                            console.log("VoiceChat: Testo pulito inviato:", cleanText);
                            if (lastSentVoiceText && cleanText && cleanText.trim() === lastSentVoiceText.trim()) {
                                setResponseText(cleanText);
                                if (addErrorMessage) addErrorMessage("Richiesta già inviata. Ignorato doppio invio vocale.");
                                return;
                            }
                            if (setLastSentVoiceText && cleanText) setLastSentVoiceText(cleanText);
                            setResponseText(cleanText);
                            if (cleanText && addUserMessage) {
                                addUserMessage(cleanText);
                                console.log("VoiceChat: Sending message history to agent endpoint...");
                                const chatRes = await fetch("http://localhost:8000/agent", {
                                    method: "POST",
                                    headers: { "Content-Type": "application/json" },
                                    body: JSON.stringify({
                                        messages: [
                                            { type: "human", content: cleanText }
                                        ]
                                    }),
                                });
                                console.log("VoiceChat: Agent response status:", chatRes.status);
                                if (chatRes.ok) {
                                    const chatData = await chatRes.json();
                                    console.log("VoiceChat: Agent response data:", chatData);
                                    const agentMsg = Array.isArray(chatData.messages)
                                        ? chatData.messages.reverse().find((m: any) => m.type === "ai" && m.content)
                                        : null;
                                    if (agentMsg && addAssistantMessage) {
                                        addAssistantMessage(agentMsg.content);

                                        // --- INIZIO: Chiamata a TTS per la risposta dell'assistente ---
                                        try {
                                            console.log("VoiceChat: Requesting TTS for assistant response:", agentMsg.content);
                                            const ttsRes = await fetch("http://localhost:8000/agent/tts", {
                                                method: "POST",
                                                headers: { "Content-Type": "application/json" },  
                                                body: JSON.stringify({ text: agentMsg.content }),
                                            });

                                            if (ttsRes.ok) {
                                                const audioBlob = await ttsRes.blob();
                                                const audioUrl = URL.createObjectURL(audioBlob);
                                                const audio = new Audio(audioUrl);
                                                audio.play().catch(e => console.error("Error playing TTS audio for assistant:", e));
                                                console.log("VoiceChat: Playing TTS audio for assistant response.");
                                                audio.onended = () => {
                                                    URL.revokeObjectURL(audioUrl);
                                                    console.log("VoiceChat: Revoked TTS audio URL for assistant response.");
                                                };
                                            } else {
                                                const ttsErrText = await ttsRes.text();
                                                console.error("VoiceChat: TTS API request failed for assistant response.", ttsRes.status, ttsErrText);
                                            }
                                        } catch (ttsErr) {
                                            console.error("VoiceChat: Error during TTS fetch operation for assistant response:", ttsErr);
                                        }
                                        // --- FINE: Chiamata a TTS ---
                                    }
                                } else {
                                    const errText = await chatRes.text();
                                    console.error("VoiceChat: Agent API request failed.", errText);
                                    if (addErrorMessage) addErrorMessage("Errore dal backend: " + errText);
                                }
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
            // Stop automatico dopo 5 secondi
            autoStopTimerRef.current = setTimeout(() => {
                if (mediaRecorderRef.current && mediaRecorderRef.current.state === "recording") {
                    console.log("VoiceChat: Auto-stopping after 5 seconds");
                    mediaRecorderRef.current.stop();
                }
            }, 5000);
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
    };

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
    return null;
};

export default VoiceChat;