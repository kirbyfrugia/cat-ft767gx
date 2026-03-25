# cat-ft767gx

I had no luck getting any combination of rigctl, flrig, hamlib etc working for wsjt-x with my Yaesu FT-767GX. I kept having issues with it error'ing out or having timing issues or simply leaving the CAT connection stuck to the point I had to yank power and battery.

I also wanted a way to program my Yaesu since sometimes I have to disconnect the battery. This allows me to do that. Well, it will someday. E.g. I'll be able to set memory stuff.

So I built a simple python program myself.

There was a fair amount of reverse engineering in this, so there might be stuff wrong.

For the wsjt-x integration, I'm mimicking the hamlib rigctl protocol. It runs a basic tcp server that responds to commands. The commands implemented are designed to deal with the exact messages I was getting from wsjt-x, so it isn't a full implementation beyond that.

For the Yaesu part, I just read the manual and implemented the protocol.

