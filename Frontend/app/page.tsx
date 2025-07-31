// // c:\Users\A58\Desktop\Progetto Tirocinio\_\Frontend\app\page.js
// 'use client';

// import React, { useState, useEffect, useRef } from 'react';
// import { useChat } from 'ai/react';
// import { Avatar } from '@readyplayerme/visage';

// export default function ChatWithAvatar() {
//   const [audioUrl, setAudioUrl] = useState('');
//   const [isSpeaking, setIsSpeaking] = useState(false);
//   const audioRef = useRef<HTMLAudioElement>(null);

//   // Il hook useChat gestisce stato, input e chiamate API
//   const { messages, input, handleInputChange, handleSubmit, isLoading } = useChat({
//     api: 'http://localhost:8000/api/chat', // Il nostro nuovo endpoint di streaming
//     async onFinish(message) {
//       // Quando l'assistente ha finito di "scrivere", generiamo l'audio
//       try {
//         const response = await fetch('http://localhost:8000/agent/tts', {
//           method: 'POST',
//           headers: { 'Content-Type': 'application/json' },
//           body: JSON.stringify({ text: message.content }),
//         });

//         if (!response.ok) throw new Error('Failed to fetch TTS audio.');

//         const blob = await response.blob();
//         const url = URL.createObjectURL(blob);
//         setAudioUrl(url);
//       } catch (error) {
//         console.error("Error during TTS:", error);
//         setIsSpeaking(false);
//       }
//     },
//   });

//   // Effetto per riprodurre l'audio quando audioUrl cambia
//   useEffect(() => {
//     if (audioUrl && audioRef.current) {
//       setIsSpeaking(true);
//       audioRef.current.play();
//     }
//   }, [audioUrl]);

//   // L'URL deve puntare direttamente al file .glb del modello.
//   // Puoi costruire l'URL corretto usando l'ID del tuo avatar.
//   const avatarId = "68722574bf6cc44ef5b3e85f";
//   const avatarUrl = `https://models.readyplayer.me/${avatarId}.glb`;

//   return (
//     <div style={styles.container}>
//       {/* Elemento audio per la riproduzione del TTS */}
//       <audio ref={audioRef} src={audioUrl} onEnded={() => setIsSpeaking(false)} hidden />

//       {/* Colonna Sinistra: Avatar 3D */}
//       <div style={styles.avatarColumn}>
//         <div style={styles.avatarContainer}>
//           <Avatar
//             modelSrc={avatarUrl}
//             shadows
//           />
//         </div>
//       </div>

//       {/* Colonna Destra: Interfaccia Chat */}
//       <div style={styles.chatColumn}>
//         <div style={styles.chatHistory}>
//           {messages.length > 0
//             ? messages.map(m => (
//               <div key={m.id} style={m.role === 'user' ? styles.userMessage : styles.assistantMessage}>
//                 <strong>{m.role === 'user' ? 'Tu' : 'Assistente'}:</strong>
//                 <p style={{ margin: 0 }}>{m.content}</p>
//               </div>
//             ))
//             : <p style={{ color: '#888' }}>Inizia la conversazione!</p>}
//           {isLoading && <div style={styles.loadingIndicator}>Sto pensando...</div>}
//         </div>

//         <form onSubmit={handleSubmit} style={styles.chatForm}>
//           <input
//             style={styles.chatInput}
//             value={input}
//             placeholder="Scrivi un messaggio..."
//             onChange={handleInputChange}
//             disabled={isLoading || isSpeaking}
//           />
//           <button type="submit" style={styles.sendButton} disabled={isLoading || isSpeaking}>Invia</button>
//         </form>
//       </div>
//     </div>
//   );
// }

// // Stili per un aspetto più gradevole
// const styles: Record<string, React.CSSProperties> = {
//   container: { display: 'flex', height: '100vh', fontFamily: 'sans-serif', background: '#f0f2f5' },
//   avatarColumn: { flex: 1, display: 'flex', justifyContent: 'center', alignItems: 'center', padding: '20px' },
//   avatarContainer: { width: '100%', height: '100%', maxWidth: '600px', maxHeight: '800px', borderRadius: '16px', overflow: 'hidden', boxShadow: '0 8px 32px rgba(0,0,0,0.1)' },
//   chatColumn: { flex: 1, display: 'flex', flexDirection: 'column', padding: '24px', borderLeft: '1px solid #ddd', background: '#fff', maxWidth: '500px' },
//   chatHistory: { flexGrow: 1, overflowY: 'auto', padding: '10px', display: 'flex', flexDirection: 'column', gap: '12px' },
//   userMessage: { alignSelf: 'flex-end', background: '#007bff', color: 'white', padding: '8px 12px', borderRadius: '18px 18px 4px 18px', maxWidth: '80%' },
//   assistantMessage: { alignSelf: 'flex-start', background: '#e9e9eb', color: 'black', padding: '8px 12px', borderRadius: '18px 18px 18px 4px', maxWidth: '80%' },
//   loadingIndicator: { alignSelf: 'flex-start', color: '#888', fontStyle: 'italic' },
//   chatForm: { display: 'flex', marginTop: '16px', gap: '10px' },
//   chatInput: { flexGrow: 1, padding: '12px', borderRadius: '8px', border: '1px solid #ccc', fontSize: '16px' },
//   sendButton: { padding: '12px 20px', borderRadius: '8px', border: 'none', background: '#007bff', color: 'white', cursor: 'pointer', fontSize: '16px' }
// };



import { Assistant } from "./assistant";

export default function Home() {
  return <Assistant />;
}


// import VoiceChat from "../components/assistant-ui/VoiceChat";

// export default function Home() {
//   return <VoiceChat />;
// }
