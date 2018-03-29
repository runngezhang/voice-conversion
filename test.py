import torch
from torch.autograd import Variable

import os
import pysptk
import pyworld
import config
import librosa
import numpy as np
from tqdm import tqdm


available_speakers = ["awb", "bdl", "clb", "jmk", "ksp", "rms", "slt"]
ssp = 'bdl'
tsp = 'slt'
path_template = "/mnt/lustre/sjtu/users/kc430/data/sjtu/tts/voice-conversion/arctic/" \
                "cmu_us_{0}_arctic/wav/cmu_us_arctic_{0}_{1}.wav"


def get_features(wav_path):
    x, fs = librosa.load(wav_path, sr=config.fs)
    x = x.astype(np.float64)
    f0, time_axis = pyworld.dio(x, fs, frame_period=config.frame_period)
    f0 = pyworld.stonemask(x, f0, time_axis, fs)
    spectrogram = pyworld.cheaptrick(x, f0, time_axis, fs)
    aperiodicity = pyworld.d4c(x, f0, time_axis, fs)
    mc = pysptk.sp2mc(spectrogram, order=config.order, alpha=config.alpha)
    return mc, aperiodicity, f0


def transform_f0(lf0_norm, ssp, tsp, f0):
    s_index = available_speakers.index(ssp)
    t_index = available_speakers.index(tsp)
    lf0 = f0.copy()
    nonzero_indices = np.nonzero(f0)
    lf0[nonzero_indices] = np.log(f0[nonzero_indices])
    lf0[nonzero_indices] = (lf0[nonzero_indices] - lf0_norm[s_index]['mean']) / lf0_norm[s_index]['std']
    lf0[nonzero_indices] = (lf0[nonzero_indices] * lf0_norm[t_index]['std']) + lf0_norm[t_index]['mean']
    f0 = lf0.copy()
    f0[nonzero_indices] = np.exp(lf0[nonzero_indices])
    return f0


def main():

    # create dir
    os.makedirs("wavs/rnn/{}_{}".format(ssp, tsp), exist_ok=True)
    # get norm of lf0
    lf0_norm = {}
    with open("/mnt/lustre/sjtu/users/kc430/data/my/vc/cmu_arctic/norm.txt", 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f.readlines()]
        for line in lines:
            line = line.split()
            lf0_norm[int(line[0])] = {'mean': float(line[1]), 'std': float(line[2])}

    checkpoint = torch.load('checkpoints/bdl-slt-rnn.cpt', map_location=lambda storage, loc: storage)
    net = checkpoint['model']

    with open('scp/test.scp', 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f.readlines()]

    for wav_id in tqdm(lines, desc='Synthesis'):
        wav_path = path_template.format(ssp, wav_id)
        mc, aperiodicity, f0 = get_features(wav_path)
        f0 = transform_f0(lf0_norm, ssp, tsp, f0)

        mc = Variable(torch.from_numpy(mc.astype(np.float32)))
        length = [len(mc)]
        mc = torch.unsqueeze(mc, dim=0)

        h, c = net.init_hidden(1)
        mc = net(mc, length, h, c)
        mc = mc.squeeze(0).data.numpy()

        spectrogram = pysptk.mc2sp(
            mc.astype(np.float64), alpha=config.alpha, fftlen=config.fftlen)
        waveform = pyworld.synthesize(
            f0, spectrogram, aperiodicity, config.fs, config.frame_period)

        maxv = np.iinfo(np.int16).max
        librosa.output.write_wav('wavs/rnn/{0}_{1}/cmu_us_arctic_{1}_{2}.wav'.format(ssp, tsp, wav_id),
                                 (waveform * maxv).astype(np.int16), config.fs)


if __name__ == '__main__':
    main()
