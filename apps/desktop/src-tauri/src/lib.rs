use std::collections::HashMap;
use std::sync::{Condvar, Mutex};
use std::time::Duration;

use serde_json::Value;
use tauri::{Emitter, Manager, State};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

struct WorkerState {
    child: Mutex<CommandChild>,
    responses: Mutex<HashMap<String, Value>>,
    response_ready: Condvar,
}

#[tauri::command]
fn worker_request(state: State<'_, WorkerState>, request: Value) -> Result<Value, String> {
    let request_id = request
        .get("request_id")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_owned();
    if request_id.is_empty() {
        return Err("request_id_required".to_owned());
    }

    let mut line = serde_json::to_vec(&request).map_err(|_| "request_serialization_failed")?;
    line.push(b'\n');
    state
        .child
        .lock()
        .map_err(|_| "worker_lock_poisoned")?
        .write(&line)
        .map_err(|_| "worker_write_failed")?;

    let mut responses = state
        .responses
        .lock()
        .map_err(|_| "response_lock_poisoned")?;
    let result = state
        .response_ready
        .wait_timeout_while(responses, Duration::from_secs(10), |pending| {
            !pending.contains_key(&request_id)
        })
        .map_err(|_| "response_wait_failed")?;
    responses = result.0;
    responses
        .remove(&request_id)
        .ok_or_else(|| "worker_response_timeout".to_owned())
        .and_then(|message| {
            if message.get("ok").and_then(Value::as_bool) == Some(true) {
                Ok(message.get("data").cloned().unwrap_or(Value::Null))
            } else {
                Err(message
                    .pointer("/error/code")
                    .and_then(Value::as_str)
                    .unwrap_or("worker_request_failed")
                    .to_owned())
            }
        })
}

fn spawn_worker(app: &tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    let sidecar = app.handle().shell().sidecar("medical-deid-worker")?;
    let (mut events, child) = sidecar.args(["--stdio"]).spawn()?;
    app.manage(WorkerState {
        child: Mutex::new(child),
        responses: Mutex::new(HashMap::new()),
        response_ready: Condvar::new(),
    });

    let handle = app.handle().clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = events.recv().await {
            if let CommandEvent::Stdout(bytes) = event {
                if let Ok(message) = serde_json::from_slice::<Value>(&bytes) {
                    if message.get("type").and_then(Value::as_str) == Some("response") {
                        if let Some(request_id) = message.get("request_id").and_then(Value::as_str)
                        {
                            let state = handle.state::<WorkerState>();
                            if let Ok(mut responses) = state.responses.lock() {
                                responses.insert(request_id.to_owned(), message.clone());
                                state.response_ready.notify_all();
                            };
                        }
                    }
                    let _ = handle.emit("worker-event", message);
                }
            }
        }
    });
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            if let Err(error) = spawn_worker(app) {
                eprintln!("worker startup failed: {error}");
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![worker_request])
        .run(tauri::generate_context!())
        .expect("error while running medical-deid");
}
