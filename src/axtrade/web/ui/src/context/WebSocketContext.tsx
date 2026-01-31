import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { ConnectionStatus, WebSocketMessage } from '../types/websocket';
import { WebSocketContext } from './context';

// Valid message types from our backend
const BACKEND_MESSAGE_TYPES = ['dashboard', 'alert', 'pnl_update', 'position_update', 'order_update', 'heartbeat'];

export const WebSocketProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [status, setStatus] = useState<ConnectionStatus>('disconnected');
    const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);
    const ws = useRef<WebSocket | null>(null);
    const reconnectTimeout = useRef<number | undefined>(undefined);
    const reconnectDelay = useRef(1000);
    const connectRef = useRef<() => void>(() => {});

    useLayoutEffect(() => {
        connectRef.current = () => {
            if (ws.current?.readyState === WebSocket.OPEN) {
                return;
            }

            setStatus('connecting');

            // Use explicit backend URL in development to avoid Vite HMR WebSocket
            const isDev = window.location.port === '5173';
            const wsUrl = isDev
                ? 'ws://127.0.0.1:8000/ws'
                : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;

            const socket = new WebSocket(wsUrl);

            socket.onopen = () => {
                // Don't set connected yet - wait for first valid message
                reconnectDelay.current = 1000;
            };

            socket.onclose = () => {
                setStatus('disconnected');
                ws.current = null;

                if (reconnectTimeout.current) {
                    clearTimeout(reconnectTimeout.current);
                }
                reconnectTimeout.current = window.setTimeout(() => {
                    reconnectDelay.current = Math.min(reconnectDelay.current * 2, 30000);
                    connectRef.current();
                }, reconnectDelay.current);
            };

            socket.onerror = () => {
                setStatus('disconnected');
            };

            socket.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    // Validate this is a message from our backend (has known type)
                    if (data && typeof data === 'object' && BACKEND_MESSAGE_TYPES.includes(data.type)) {
                        setStatus('connected');
                        setLastMessage(data as WebSocketMessage);
                    }
                } catch {
                    // Ignore non-JSON messages
                }
            };

            ws.current = socket;
        };
    });

    useEffect(() => {
        connectRef.current();

        return () => {
            if (ws.current) {
                ws.current.close();
            }
            if (reconnectTimeout.current) {
                clearTimeout(reconnectTimeout.current);
            }
        };
    }, []);

    const sendMessage = useCallback((msg: Record<string, unknown>) => {
        if (ws.current?.readyState === WebSocket.OPEN) {
            ws.current.send(JSON.stringify(msg));
        }
    }, []);

    return (
        <WebSocketContext.Provider value={{ status, lastMessage, sendMessage }}>
            {children}
        </WebSocketContext.Provider>
    );
};
