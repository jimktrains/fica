#!/usr/bin/env python3
import time
import magic
import mimetypes
import os
import hashlib
import re
import csv
from PIL import Image
from PIL import ExifTags
import io
import json
from hsaudiotag import auto
from hsaudiotag import mpeg
from hsaudiotag import ogg
from hsaudiotag import mp4

BLOCKSIZE = 65536

#hasher = hashlib.sha512()

# Using MD5 because that's what S3 uses
# and part of these files will be uploaded
# and I would like to use the hash to both 
# dedup and check if it's been uploaded
# and I have the sizes and hashes for my
# S3 files already. Collisions shouldn't
# be a terribly large problem since I'm
# not worried about forced collisions
hasher = hashlib.md5()

clean_mime = re.compile('[^A-Za-z0-9. -]')

with open('/dev/stdin', 'w') as csvfile:
    csvw = csv.writer(csvfile)
    for dirname, dirnames, filenames in os.walk('.'):
        for filename in filenames:
            filename = os.path.join(dirname, filename)
            
            # Guesses MIME based on filename
            mimetype_ext = mimetypes.guess_type(filename)[0]

            mimetype_long = mimetype_ext
            mimetype = mimetype_ext
            first_block = True
            meta = {}
            last_buf = None
            last_two = b""
            with open(filename, 'rb') as afile:
                buf = afile.read(BLOCKSIZE)
                while len(buf) > 0:
                    hasher.update(buf)

                    # Find metadata about common file types
                    # We're just using the first (64k) block
                    # but that's sufficent for audio and EXIF
                    # tags
                    if first_block:
                        # Use libmagic to analize the first block in order
                        # to determine a better guess at the mime than
                        # by file extention above
                        mimetype_long = magic.from_buffer(buf)
                        mimetype_long = mimetype_long.decode("utf-8")
                        # Seems to not be the same as when mime=False?
                        mimetype = magic.from_buffer(buf, mime=True)
                        mimetype = mimetype.decode("utf-8")

                        # BytesIO because these methods take file-descriptors
                        # and I don't want to have to double-read any bytes
                        # since this is going to be done over USB
                        bufio = io.BytesIO(buf);

                        # Find the EXIF Time and resolution
                        #  Time will be used to sort and name 
                        #  (parent directory for) pictures.
                        # Resolution is used to check if I want
                        #  to make a thumbnail
                        if mimetype and ('jpeg' in mimetype):
                            img = Image.open(bufio)
                            for k,v in img._getexif().items():
                                if k in ( 40962, 40963): #width, height
                                    meta[ExifTags.TAGS[k]] = v
                                elif k == 306: #date
                                    meta[ExifTags.TAGS[k]] = time.strptime(v, '%Y:%m:%d %H:%M:%S')

                        # Find tags in audio formats
                        # I would like to organize the files as
                        # <artist>/<album>/<track>-<title>
                        if mimetype and ('audio' in mimetype or 'ogg' in mimetype):
                            aud = auto.File(bufio)

                            meta['artist'] = aud.artist
                            if type(meta['artist']) == bytes:
                                meta['artist'] = meta['artist'].decode('utf-8')
                            meta['album'] = aud.album
                            if type(meta['album']) == bytes:
                                meta['album'] = meta['album'].decode('utf-8')
                            meta['title'] = aud.title
                            if type(meta['title']) == bytes:
                                meta['title'] = meta['title'].decode('utf-8')
                            meta['track'] = aud.track
                            #if type(meta['track']) == bytes:
                            #    meta['track'] = meta['track'].decode('utf-8')
                            #meta['year'] = aud.year
                            #if type(meta['year']) == bytes:
                            #    meta['year'] = meta['year'].decode('utf-8')
                        first_block = False

                    # I originally thought that I may need to store the last
                    # block or two incase some format stores it at the end
                    if last_buf is not None:
                        last_two = last_buf
                    last_buf = buf

                    buf = afile.read(BLOCKSIZE)

            hash_hex = hasher.hexdigest()
            
            # Grab some traditionall file states
            # like the size and creation time
            stat = os.stat(filename)
            fsize = stat.st_size
            ctime = stat.st_ctime

            csvw.writerow([
                  filename,
                  mimetype,
                  mimetype_long,
                  fsize,
                  ctime,
                  hash_hex,
                  json.dumps(meta)
            ])

