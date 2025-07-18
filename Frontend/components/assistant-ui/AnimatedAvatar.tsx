import React, { useEffect, useRef } from 'react';
import Image from 'next/image';
import { cn } from '@/lib/utils';

type AnimatedAvatarProps = {
  videoUrl: string | null;
  onVideoEnd: () => void;
  className?: string;
  imageClassName?: string;
  objectFit?: 'cover' | 'contain' | 'fill' | 'none' | 'scale-down';
};

export const AnimatedAvatar: React.FC<AnimatedAvatarProps> = ({
  videoUrl,
  onVideoEnd,
  className,
  imageClassName,
  objectFit = 'cover',
}) => {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (videoUrl && videoRef.current) {
      videoRef.current.load();
      videoRef.current.play().catch(e => console.error("Errore durante la riproduzione del video dell'avatar:", e));
    }
  }, [videoUrl]);

  return (
    <div className={cn('relative', className)}>
      {videoUrl ? (
        <video
          ref={videoRef}
          src={videoUrl}
          onEnded={onVideoEnd}
          className={cn('h-full w-full', imageClassName)}
          style={{ objectFit }}
          playsInline
          muted={false} // Assicurati che l'audio del video sia riprodotto
        />
      ) : (
        <Image
          src={process.env.NEXT_PUBLIC_AVATAR_URL || '/images/avatar.png'}
          alt="Assistente virtuale"
          fill
          style={{ objectFit }}
          className={cn(imageClassName)}
          priority
        />
      )}
    </div>
  );
};

export default AnimatedAvatar;

