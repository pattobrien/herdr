use super::*;

/// Internal events for the client event loop.
pub(super) enum ClientLoopEvent {
    #[cfg(unix)]
    StdinInput(Vec<u8>),
    #[cfg(unix)]
    PixelMouse(Vec<u8>, crate::input::mouse::HostGeometry),
    #[cfg(unix)]
    DirectGraphicsResponse(direct_graphics::Response),
    #[cfg(windows)]
    StdinEvents(Vec<crate::protocol::ClientInputEvent>),
    #[cfg(windows)]
    NotificationActivated(shell::ClientSystemNotificationTarget),
    Resize(u16, u16, u32, u32, bool),
    TerminalUnavailable(io::Error),
    ServerMessage {
        endpoint_id: endpoint::ClientEndpointId,
        generation: u64,
        message: Box<ServerMessage>,
    },
    ServerDisconnected {
        endpoint_id: endpoint::ClientEndpointId,
        generation: u64,
    },
    EndpointSupervisor(endpoint::EndpointSupervisorEvent),
    EndpointCatalog(Result<Vec<endpoint::SavedSshEndpoint>, String>),
    ActivateEndpoint {
        endpoint_id: endpoint::ClientEndpointId,
        target: Option<shell::ClientEndpointFocusTarget>,
        /// A superseded handoff deliberately starts a fresh target-on epoch even when source and
        /// latest target have the same identity after restoration.
        force: bool,
    },
    Timer,
}

/// Input and supervisor events win over queued server frames; a frame burst
/// then blocks the reader thread instead of delaying keystrokes.
#[cfg(unix)]
pub(super) async fn next_loop_event(
    timer_deadline: std::time::Instant,
    supervisor_rx: &mut tokio::sync::mpsc::Receiver<endpoint::EndpointSupervisorEvent>,
    event_rx: &mut tokio::sync::mpsc::Receiver<ClientLoopEvent>,
    server_rx: &mut tokio::sync::mpsc::Receiver<ClientLoopEvent>,
) -> ClientLoopEvent {
    tokio::select! {
        biased;
        _ = tokio::time::sleep_until(timer_deadline.into()) => ClientLoopEvent::Timer,
        ev = supervisor_rx.recv() => ev.map(ClientLoopEvent::EndpointSupervisor).unwrap_or(ClientLoopEvent::Timer),
        ev = event_rx.recv() => ev.unwrap_or(ClientLoopEvent::Timer),
        ev = server_rx.recv() => ev.unwrap_or(ClientLoopEvent::Timer),
    }
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;

    fn server_message() -> ClientLoopEvent {
        ClientLoopEvent::ServerMessage {
            endpoint_id: endpoint::ClientEndpointId::Local,
            generation: 1,
            message: Box::new(ServerMessage::ReloadSoundConfig),
        }
    }

    #[tokio::test(flavor = "current_thread")]
    async fn input_is_delivered_before_queued_server_frames() {
        let (_supervisor_tx, mut supervisor_rx) = tokio::sync::mpsc::channel(1);
        let (event_tx, mut event_rx) = tokio::sync::mpsc::channel(4);
        let (server_tx, mut server_rx) = tokio::sync::mpsc::channel(2);
        server_tx.try_send(server_message()).unwrap();
        server_tx.try_send(server_message()).unwrap();
        assert!(server_tx.try_send(server_message()).is_err());
        event_tx
            .try_send(ClientLoopEvent::StdinInput(b"a".to_vec()))
            .unwrap();
        let deadline = std::time::Instant::now() + Duration::from_secs(60);

        let first = next_loop_event(deadline, &mut supervisor_rx, &mut event_rx, &mut server_rx);
        assert!(matches!(first.await, ClientLoopEvent::StdinInput(_)));
        let second = next_loop_event(deadline, &mut supervisor_rx, &mut event_rx, &mut server_rx);
        assert!(matches!(
            second.await,
            ClientLoopEvent::ServerMessage { generation: 1, .. }
        ));
        let third = next_loop_event(deadline, &mut supervisor_rx, &mut event_rx, &mut server_rx);
        assert!(matches!(
            third.await,
            ClientLoopEvent::ServerMessage { generation: 1, .. }
        ));
    }
}
