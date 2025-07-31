// C:\Users\A58\Desktop\Progetto Tirocinio\_\Frontend\app\api\generate-video\route.ts

import { NextResponse } from 'next/server';
import { generateDIdVideo } from '@/lib/did'; // Importiamo la nostra funzione helper

export async function POST(request: Request) {
    try {
        // 1. Estrai il testo dal corpo della richiesta
        const { text } = await request.json();

        if (!text) {
            return NextResponse.json(
                { error: 'Text is required' },
                { status: 400 }
            );
        }

        // 2. Chiama la nostra funzione helper per generare il video
        console.log(`Received request to generate video for text: "${text}"`);
        const videoUrl = await generateDIdVideo(text);

        // 3. Gestisci la risposta
        if (videoUrl) {
            // Se abbiamo un URL, lo restituiamo al frontend
            return NextResponse.json({ videoUrl });
        } else {
            // Se qualcosa è andato storto, restituiamo un errore
            return NextResponse.json(
                { error: 'Failed to generate video' },
                { status: 500 }
            );
        }
    } catch (error) {
        console.error('/api/generate-video error:', error);
        return NextResponse.json(
            { error: 'An internal server error occurred' },
            { status: 500 }
        );
    }
}
