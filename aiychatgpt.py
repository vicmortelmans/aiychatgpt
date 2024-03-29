#!/usr/bin/env python3
import argparse
from dotenv import load_dotenv
import getpass
import locale
import logging
import os
from queue import Queue
from threading import Thread, Lock
import uuid

from gtts import gTTS

from util import Button, Led
from aiy.voice import tts
from aiy.cloudspeech import CloudSpeechClient
# to make this work, a change of the aiy module was needed
# in cloudspeech.py, the hardcoded settings of the audio device are configured
# to match the AIY Voice HAT, but I'm using some cheap USB audio adapter now
# AUDIO_SAMPLE_RATE_HZ = 48000
# AUDIO_FORMAT=AudioFormat(sample_rate_hz=AUDIO_SAMPLE_RATE_HZ,
#                          num_channels=1,
#                          bytes_per_sample=2)

from openai import OpenAI

logging.basicConfig(format='%(asctime)s,%(msecs)d %(levelname)-8s [%(filename)s:%(lineno)d %(funcName)s] %(message)s', datefmt='%Y-%m-%d:%H:%M:%S', level=logging.DEBUG)

load_dotenv("/home/pi/.env")  # contains OPENAI_API_KEY
AI = OpenAI()
sentences_text = Queue()
sentences_mp3 = Queue()
lock = Lock()

def converter():
    while True:
        sentence_text = sentences_text.get()
        logging.info(f"Converting '{sentence_text}' to mp3")
        sentence_mp3 = f"/tmp/{str(uuid.uuid4())}.mp3"
        tts = gTTS(sentence_text, lang="nl")
        tts.save(sentence_mp3)
        logging.info(f"Storing '{sentence_text}' as {sentence_mp3}")
        sentences_mp3.put(sentence_mp3)

def speaker():
    while True:
        sentence_mp3 = sentences_mp3.get()
        logging.info(f"Speaking {sentence_mp3}")
        os.system(f"madplay {sentence_mp3}") 
        #os.remove(sentence_mp3)
        if sentences_mp3.empty() and sentences_text.empty(): 
            logging.info("Speech is finished completely")
            lock.release()

def main():
    logging.info(f"Running as {getpass.getuser()}")

    client = CloudSpeechClient()

    converter_thread = Thread(target=converter)
    speaker_thread = Thread(target=speaker)
    converter_thread.start()
    speaker_thread.start()

    messages = [
        {"role": "system", "content": "Je bent een intellectuele gesprekspartner met conservatieve ideeën"}
    ] 

    times_hearing_nothing = 0

    with Led(channel=17) as led, Button(channel=27) as button:
        while True:
            lock.acquire()
            if times_hearing_nothing > 3:
                logging.info("Silence... resetting conversation and waiting for button to start listening again")
                times_hearing_nothing = 0
                # reset conversation
                messages = [
                    {"role": "system", "content": "Je bent een vleierige dienaar"}
                ] 
                button.wait_for_press()
            led.state = Led.ON
            logging.info("Start listening")
            text = client.recognize(language_code="nl")
            led.state = Led.OFF
            if text is None:
                logging.info('You said nothing.')
                times_hearing_nothing += 1
                lock.release()
                continue

            logging.info('You said: "%s"' % text)

            messages.append({"role": "user", "content": text})
            completion = AI.chat.completions.create(
              model="gpt-3.5-turbo",
              messages=messages,
              stream=True
            )

            answer = ""

            for chunk in completion:
                if chunk.choices[0].delta.content == None:
                    sentences_text.put(answer)
                    break
                answer += chunk.choices[0].delta.content
                if ". " in answer:
                    (sentence, answer) = answer.split(". ", maxsplit=1)
                    sentences_text.put(sentence)

            logging.info(f"Adding answer to conversation: '{answer}'")
            messages.append({"role": "assistant", "content": answer})


if __name__ == '__main__':
    main()
