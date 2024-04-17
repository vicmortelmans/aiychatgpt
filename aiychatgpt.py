#!/usr/bin/env python3
import argparse
from dotenv import load_dotenv
import getpass
import locale
import logging
import os
from queue import Queue
import subprocess
from sys import stdout
from threading import Thread
import uuid

from google.cloud import texttospeech

from util import Button, Led
#from aiy.voice import tts
from aiy.cloudspeech import CloudSpeechClient
# to make this work, a change of the aiy module was needed
# in cloudspeech.py, the hardcoded settings of the audio device are configured
# to match the AIY Voice HAT, but I'm using some cheap USB audio adapter now
# AUDIO_SAMPLE_RATE_HZ = 48000
# AUDIO_FORMAT=AudioFormat(sample_rate_hz=AUDIO_SAMPLE_RATE_HZ,
#                          num_channels=1,
#                          bytes_per_sample=2)

from openai import OpenAI


logger = logging.getLogger("aichatgpt")
handler = logging.StreamHandler(stdout)
handler.setFormatter(logging.Formatter(fmt='%(asctime)s,%(msecs)d %(levelname)-8s [%(filename)s:%(lineno)d %(funcName)s] %(message)s', datefmt='%Y-%m-%d:%H:%M:%S'))
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)

load_dotenv(os.getenv('HOME') + "/.env")  # contains OPENAI_API_KEY
AI = OpenAI()
tts_client = texttospeech.TextToSpeechClient()
sentences_text = Queue()
sentences_mp3 = Queue()
led = Led(channel=17)
button = Button(channel=27)
client = CloudSpeechClient()
role = "Je bent een stemgestuurde assistent." 
messages = [ {"role": "system", "content": role} ] 
state = "IDLE"
speaking_process = None

def converter():
    while True:
        # wait until a new sentence is added to the queue
        sentence_text = sentences_text.get()  # BLOCKING
        logger.info(f"Converting '{sentence_text}' to mp3")
        sentence_mp3 = f"/tmp/{str(uuid.uuid4())}.mp3"
        synthesis_input = texttospeech.SynthesisInput(text=sentence_text)
        voice = texttospeech.VoiceSelectionParams(language_code="nl-BE")
        audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
        response = tts_client.synthesize_speech(input=synthesis_input, voice=voice, audio_config=audio_config)
        logger.info(f"Storing '{sentence_text}' as {sentence_mp3}")
        with open(sentence_mp3, "wb") as out:
            out.write(response.audio_content)
        sentences_mp3.put(sentence_mp3)

def speaker():
    global speaking_process

    while True:
        # wait until a new mp3 is added to the queue
        sentence_mp3 = sentences_mp3.get()  # BLOCKING
        logger.info(f"Speaking {sentence_mp3}")
        speaking_process = subprocess.Popen(['mpg123','-q',sentence_mp3])
        speaking_process.wait()
        speaking_process = None
        os.remove(sentence_mp3)
        if sentences_mp3.empty() and sentences_text.empty() and state == "TALKING": 
            logger.info("Speech is finished completely")
            converse()

def converse():
    global state
    global button
    global led
    global messages

    state = "LISTENING"
    led.state = Led.ON
    for i in [1,2,3]:
        logger.info("Start listening")
        text = client.recognize(language_code="nl")  # BLOCKING
        if text:
            break
    else:  # no break
        logger.info("Silence... resetting conversation and waiting for button to start listening again")
        # reset conversation
        logger.info("Conversation reset")
        messages = [
            {"role": "system", "content": role}
        ] 
        state = "IDLE"
        led.state = Led.OFF
        return
    # process question
    state = "THINKING"
    led.state = Led.BLINK_3
    logger.info('You said: "%s"' % text)
    messages.append({"role": "user", "content": text})
    completion = AI.chat.completions.create(
      model="gpt-3.5-turbo",
      messages=messages,
      stream=True
    )
    answer = ""
    partial_answer = ""
    for chunk in completion:
        if chunk.choices[0].delta.content == None:
            # no more content; answer is complete
            sentences_text.put(partial_answer)
            answer += partial_answer
            break
        partial_answer += chunk.choices[0].delta.content
        if ". " in partial_answer:
            # submit finished sentence for converting and speaking
            (sentence, partial_answer) = partial_answer.split(". ", maxsplit=1)
            sentences_text.put(sentence)
            answer += sentence
    logger.info(f"Adding answer to conversation: '{answer}'")
    messages.append({"role": "assistant", "content": answer})
    state = "TALKING"
    led.state = Led.OFF

        
def main():
    global state
    global sentences_text
    global sentences_mp3
    global button
    global speaking_process

    logger.info(f"Running as {getpass.getuser()}")

    converter_thread = Thread(target=converter)
    speaker_thread = Thread(target=speaker)
    converter_thread.start()
    speaker_thread.start()

    while True:
        logger.info("Waiting for button")
        button.wait_for_press()  # BLOCKING
        if state == "IDLE":
            converse()
        elif state == "TALKING":
            state = "CANCELLING"
            logger.info("Clearing talking queues")
            sentences_text.queue.clear()
            sentences_mp3.queue.clear()
            if speaking_process:
                speaking_process.kill()
            converse()


if __name__ == '__main__':
    main()
