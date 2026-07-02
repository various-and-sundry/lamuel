import pyaudio

def list_audio_input_devices():
    p = pyaudio.PyAudio()
    print("Audio Input Devices:")
    for i in range(p.get_device_count()):
        device_info = p.get_device_info_by_index(i)
        if device_info['maxInputChannels'] > 0:  # Check if the device has input channels
            print(f"Device {i}: {device_info['name']} (Input Channels: {device_info['maxInputChannels']})")
    p.terminate()

list_audio_input_devices()

