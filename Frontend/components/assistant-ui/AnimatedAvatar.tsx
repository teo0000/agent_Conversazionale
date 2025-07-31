
import React, { useEffect, useRef, useState } from "react";
import { Avatar } from '@readyplayerme/visage';
import { createPortal } from "react-dom";


const avatarId = "68722574bf6cc44ef5b3e85f";
const avatarUrl = `https://models.readyplayer.me/${avatarId}.glb`;

interface AnimatedAvatarProps {
    isSpeaking?: boolean;
}

/**
 * AnimatedAvatar: avatar 3D con animazione braccia e viso (jaw) durante il parlato.
 * L'animazione viene attivata tramite la prop isSpeaking.
 */
export default function AnimatedAvatar({ isSpeaking = false }: AnimatedAvatarProps) {

    const [isMounted, setIsMounted] = useState(false);

    useEffect(() => {
        // Questo assicura che il codice venga eseguito solo sul client, evitando problemi con SSR
        setIsMounted(true);
    }, []);

    const jawBoneRef = useRef<any>(null);
    const leftArmRef = useRef<any>(null);
    const rightArmRef = useRef<any>(null);
    const modelRef = useRef<any>(null);

    // Polling per trovare il modello 3D ReadyPlayerMe
    useEffect(() => {
        let interval: NodeJS.Timeout;
        let tentativi = 0;
        function cercaModello() {
            // Cerca la scena three.js globale (ReadyPlayerMe la espone su window.scene)
            // oppure cerca window.avatar/model, oppure cerca tra i renderer
            // Qui tentiamo con window.scene
            // @ts-ignore
            const scene = (window as any).scene;
            if (scene && scene.children) {
                // Cerca il root mesh/avatar
                const avatar = scene.children.find((obj: any) => obj.type === "Group" && obj.children.some((c: any) => c.name && c.name.toLowerCase().includes("armature")));
                if (avatar) {
                    modelRef.current = avatar;
                    jawBoneRef.current = avatar.getObjectByName("Head_jaw") || avatar.getObjectByName("Jaw") || null;
                    leftArmRef.current = avatar.getObjectByName("LeftArm") || avatar.getObjectByName("mixamorig:LeftArm") || null;
                    rightArmRef.current = avatar.getObjectByName("RightArm") || avatar.getObjectByName("mixamorig:RightArm") || null;
                    clearInterval(interval);
                }
            }
            tentativi++;
            if (tentativi > 50) clearInterval(interval); // timeout dopo 5s
        }
        interval = setInterval(cercaModello, 100);
        return () => clearInterval(interval);
    }, []);

    useEffect(() => {

        let frameId: number;
        let t = 0;

        function animate() {
            t += 0.1;
            // Muovi la jaw (mandibola) su/giù per simulare il parlato
            if (jawBoneRef.current) {
                jawBoneRef.current.rotation.x = isSpeaking ? 0.15 + 0.07 * Math.sin(t * 8) : 0;
            }
            // Muovi le braccia (oscillazione semplice)
            if (leftArmRef.current) {
                leftArmRef.current.rotation.z = isSpeaking ? 0.2 * Math.sin(t * 2) : 0;
            }
            if (rightArmRef.current) {
                rightArmRef.current.rotation.z = isSpeaking ? -0.2 * Math.sin(t * 2) : 0;
            }
            frameId = requestAnimationFrame(animate);
        }
        animate();
        return () => cancelAnimationFrame(frameId);
    }, [isSpeaking]);

    // Non renderizzare nulla sul server o prima del montaggio sul client
    if (!isMounted) {
        return null;
    }

    // Creiamo l'elemento Avatar che verrà renderizzato nel portale
    const avatarElement = (
        <Avatar
            modelSrc={avatarUrl}
            style={{
                position: 'fixed',
                top: '50%',
                left: '20px',
                transform: 'translateY(-50%)',
                zIndex: 1000,
                width: 220,
                height: 550,
                // Aggiungi un bordo o uno sfondo se vuoi testarne la visibilità
                // border: '2px solid red' 
            }}
            shadows />
    );

    // Usiamo createPortal per renderizzare l'avatar direttamente nel body del documento
    return createPortal(avatarElement, document.body);
}
