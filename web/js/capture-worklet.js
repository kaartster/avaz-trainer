// Runs on the audio thread. Collects the 128-sample render quanta of the mic into
// larger blocks and posts each block to the main thread, with its loudness.

class CaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.size = (options.processorOptions && options.processorOptions.blockSize) || 512;
    this.buf = new Float32Array(this.size);
    this.count = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;
    for (let i = 0; i < channel.length; i++) {
      this.buf[this.count++] = channel[i];
      if (this.count === this.size) {
        this.port.postMessage(this.buf);
        this.buf = new Float32Array(this.size);
        this.count = 0;
      }
    }
    return true;
  }
}

registerProcessor("capture", CaptureProcessor);
