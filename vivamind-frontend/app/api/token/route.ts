import { NextResponse } from 'next/server';
import {
  AccessToken,
  type AccessTokenOptions,
  type VideoGrant,
} from 'livekit-server-sdk';
import { RoomConfiguration } from '@livekit/protocol';

type ConnectionDetails = {
  serverUrl: string;
  roomName: string;
  participantName: string;
  participantToken: string;
};

const API_KEY = process.env.LIVEKIT_API_KEY;
const API_SECRET = process.env.LIVEKIT_API_SECRET;
const LIVEKIT_URL = process.env.LIVEKIT_URL;

// Don't cache the results
export const revalidate = 0;

export async function POST(req: Request) {
  try {
    // Validate required environment variables
    if (!LIVEKIT_URL) {
      throw new Error('LIVEKIT_URL is not defined');
    }

    if (!API_KEY) {
      throw new Error('LIVEKIT_API_KEY is not defined');
    }

    if (!API_SECRET) {
      throw new Error('LIVEKIT_API_SECRET is not defined');
    }

    // Parse room config from request body
    const body = await req.json();

    const roomConfig = body?.room_config
      ? RoomConfiguration.fromJson(body.room_config, {
          ignoreUnknownFields: true,
        })
      : new RoomConfiguration();

    // Generate participant info
    const participantName = 'user';
    const participantIdentity = `voice_assistant_user_${Math.floor(
      Math.random() * 10000
    )}`;
    const roomName = `voice_assistant_room_${Math.floor(
      Math.random() * 10000
    )}`;

    // Create LiveKit token
    const participantToken = await createParticipantToken(
      {
        identity: participantIdentity,
        name: participantName,
      },
      roomName,
      roomConfig
    );

    const data: ConnectionDetails = {
      serverUrl: LIVEKIT_URL,
      roomName,
      participantName,
      participantToken,
    };

    return NextResponse.json(data, {
      headers: {
        'Cache-Control': 'no-store',
      },
    });
  } catch (error) {
    console.error('Token generation failed:', error);

    return NextResponse.json(
      {
        error:
          error instanceof Error ? error.message : 'Unknown server error',
      },
      {
        status: 500,
      }
    );
  }
}

function createParticipantToken(
  userInfo: AccessTokenOptions,
  roomName: string,
  roomConfig?: RoomConfiguration
): Promise<string> {
  const at = new AccessToken(API_KEY!, API_SECRET!, {
    ...userInfo,
    ttl: '15m',
  });

  const grant: VideoGrant = {
    room: roomName,
    roomJoin: true,
    canPublish: true,
    canPublishData: true,
    canSubscribe: true,
  };

  at.addGrant(grant);

  if (roomConfig) {
    at.roomConfig = roomConfig;
  }

  return at.toJwt();
}