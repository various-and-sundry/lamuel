import pyaudio
import vosk
import json
import ollama
import subprocess
import threading
import os
import re
import cv2
import time

class AudioRecognizer:
    def __init__(self, model_path, device_index=1, samplerate=44100, chunk_size=8000):
        # Set up the Vosk model
        self.model = vosk.Model(model_path)

        # Initialize PyAudio
        self.p = pyaudio.PyAudio()

        # Get device info
        device_info = self.p.get_device_info_by_index(device_index)
        self.samplerate = int(device_info['defaultSampleRate'])  # Use the default sample rate
        self.chunk_size = chunk_size

        # Open the audio stream
        self.stream = self.p.open(format=pyaudio.paInt16,
                                   channels=1,
                                   rate=self.samplerate,
                                   input=True,
                                   input_device_index=device_index,
                                   frames_per_buffer=self.chunk_size)
        self.stream.start_stream()

        # Initialize the recognizer
        self.rec = vosk.KaldiRecognizer(self.model, self.samplerate)

    def listen(self, chat_callback):
        print("Listening...")
        try:
            while True:
                data = self.stream.read(self.chunk_size, exception_on_overflow=False)
                if self.rec.AcceptWaveform(data):
                    result = self.rec.Result()
                    user_input = json.loads(result)["text"]
                    if user_input.strip() and user_input != "huh":
                        chat_callback(user_input)  # Pass the recognized text to the chat function
                else:
                    partial_result = self.rec.PartialResult()
                    print(json.loads(partial_result)["partial"])
        except KeyboardInterrupt:
            print("\nStopped by user")
        except Exception as e:
            print(f"An error occurred: {e}")
        finally:
            self.stop()

    def stop(self):
        self.stream.stop_stream()
        self.stream.close()
        self.p.terminate()
        print("Audio stream stopped.")

# Initialize chat messages
chat_messages = []
system_message = ''

def create_message(message, role):
    return {
        'role': role,
        'content': message
    }

def create_image_message(message, role, image):
    return {
        'role': role,
        'content': message,
        'images': [image]
    }


# Function to handle the chat process
def chat(user_input):
    # Print what was heard
    print(f"User said: {user_input}")

    image_path = "/tmp/image.jpg"
    semaphore_path = "/tmp/GETIMG"

    # Create the file
    with open(semaphore_path, 'w') as f:
        f.write('This is a temporary file.')

    print(f'File created at {semaphore_path}. Waiting for it to be deleted...')

    # Wait until the file is deleted
    while os.path.exists(semaphore_path):
        time.sleep(0.1)  # Check every second

    print('File has been deleted.')

    # Append user input to chat messages
    chat_messages.append(create_message(user_input + image_path, 'user'))

    # Call the ollama API to get the assistant response
    ollama_response = ollama.chat(model='lamuel', stream=True, messages=chat_messages)

    # Preparing the assistant message by concatenating all received chunks from the API
    assistant_message = ''
    for chunk in ollama_response:
        assistant_message += chunk['message']['content']

    message = re.sub(r'\b(HEAD-YAW|Head-Yaw|HEAD-PITCH|Head-Pitch)', r'\n\1', assistant_message)
    message_without_asterisks = re.sub(r'\*', '', message)

    # Split the assistant message into lines for processing
    lines = message_without_asterisks.splitlines()

    for line in lines:
        line = line.strip()  # Remove leading/trailing whitespace
        if line.startswith('HEAD-YAW'):
            print(line)
        elif line.startswith('HEAD-PITCH'):
            print(line)
        else:
            print(line)
            # Call the flite command with the extracted text, save to a temporary file, and play it
            temp_wav_path = "/tmp/tmp.wav"
            subprocess.run(['flite', '"' + line + ' "', '-o', temp_wav_path])

            if os.path.exists(temp_wav_path):
                # Start a new thread for playing the audio
                audio_thread = threading.Thread(target=play_audio, args=(temp_wav_path,))
                audio_thread.start()

                # Wait for the audio thread to finish
                audio_thread.join()
                os.remove(temp_wav_path)

    # Adding the finalized assistant message to the chat log
    chat_messages.append(create_message(assistant_message, 'assistant'))

def play_audio(file_path):
    subprocess.run(['mpv', file_path])

def main():
    model_path = "vosk-model-small-en-us-0.15/"
    recognizer = AudioRecognizer(model_path)

    # Start listening for audio input and handle chat
    recognizer.listen(chat)

if __name__ == "__main__":
    main()
