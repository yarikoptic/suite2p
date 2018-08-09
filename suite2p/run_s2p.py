import numpy as np
import time, os
from suite2p import register, dcnv
from suite2p import celldetect2 as celldetect2
from scipy import stats
from multiprocessing import Pool

def tic():
    return time.time()
def toc(i0):
    return time.time() - i0

def default_ops():
    ops = {
        'fast_disk': [], # used to store temporary binary file, defaults to save_path0
        'delete_bin': False, # whether to delete binary file after processing
        'h5py': [], # take h5py as input (deactivates data_path)
        'h5py_key': 'data', #key in h5py where data array is stored
        'save_path0': [], # stores results, defaults to first item in data_path
        'diameter':12, # this is the main parameter for cell detection
        'tau':  1., # this is the main parameter for deconvolution
        'fs': 10.,  # sampling rate (total across planes)
        'nplanes' : 1, # each tiff has these many planes in sequence
        'nchannels' : 1, # each tiff has these many channels per plane
        'functional_chan' : 1, # this channel is used to extract functional ROIs (1-based)
        'align_by_chan' : 1, # when multi-channel, you can align by non-functional channel (1-based)
        'look_one_level_down': False, # whether to look in all subfolders when searching for tiffs
        'baseline': 'maximin', # baselining mode
        'win_baseline': 60., # window for maximin
        'sig_baseline': 10., # smoothing constant for gaussian filter
        'prctile_baseline': 8.,# smoothing constant for gaussian filter
        'neucoeff': .7,  # neuropil coefficient
        'neumax': 1.,  # maximum neuropil coefficient (not implemented)
        'niterneu': 5, # number of iterations when the neuropil coefficient is estimated (not implemented)
        'maxregshift': 0.1, # max allowed registration shift, as a fraction of frame max(width and height)
        'subpixel' : 10, # precision of subpixel registration (1/subpixel steps)
        'batch_size': 200, # number of frames per batch
        'num_workers': 0, # 0 to select num_cores, -1 to disable parallelism, N to enforce value
        'num_workers_roi': -1, # 0 to select number of planes, -1 to disable parallelism, N to enforce value
        'nimg_init': 200, # subsampled frames for finding reference image
        'navg_frames_svd': 5000, # max number of binned frames for the SVD
        'nsvd_for_roi': 1000, # max number of SVD components to keep for ROI detection
        'max_iterations': 10, # maximum number of iterations to do cell detection
        'ratio_neuropil': 6., # ratio between neuropil basis size and cell radius
        'tile_factor': 1., # use finer (>1) or coarser (<1) tiles for neuropil estimation
        'threshold_scaling': 1., # adjust the automatically determined threshold by this scalar multiplier
        'inner_neuropil_radius': 2, # number of pixels to keep between ROI and neuropil donut
        'outer_neuropil_radius': np.inf, # maximum neuropil radius
        'min_neuropil_pixels': 350, # minimum number of pixels in the neuropil
        'ratio_neuropil_to_cell': 3, # minimum ratio between neuropil radius and cell radius
        'allow_overlap': False,
        'combined': True, # combine multiple planes into a single result /single canvas for GUI
        'max_overlap': 0.75, # cells with more overlap than this get removed during triage, before refinement
        'xrange': np.array([0, 0]),
        'yrange': np.array([0, 0]),
      }
    return ops

def get_cells(ops):
    i0 = tic()
    ops, stat = celldetect2.sourcery(ops)
    print('time %4.4f. Found %d ROIs'%(toc(i0), len(stat)))
    # extract fluorescence and neuropil
    F, Fneu = celldetect2.extractF(ops, stat)
    print('time %4.4f. Extracted fluorescence from %d ROIs'%(toc(i0), len(stat)))

    # subtract neuropil
    dF = F - ops['neucoeff'] * Fneu
    # compute activity statistics for classifier
    sk = stats.skew(dF, axis=1)
    for k in range(F.shape[0]):
        stat[k]['skew'] = sk[k]

    # save results
    np.save(ops['ops_path'], ops)
    fpath = ops['save_path']
    np.save(os.path.join(fpath,'F.npy'), F)
    np.save(os.path.join(fpath,'Fneu.npy'), Fneu)
    np.save(os.path.join(fpath,'stat.npy'), stat)
    iscell = np.ones((len(stat),2))
    np.save(os.path.join(fpath, 'iscell.npy'), iscell)
    print('results saved to %s'%ops['save_path'])
    return ops

def combined(ops1):
    '''
    Combines all the entries in ops1 into a single result file. Multi-plane recordings are arranged to best tile a square.

    Multi-roi recordings will be arranged by their physical localization.

    '''
    ops = ops1[0]
    Lx = ops['Lx']
    Ly = ops['Ly']
    nX = np.ceil(np.sqrt(ops['Ly'] * ops['Lx'] * len(ops1))/ops['Lx'])
    nX = int(nX)
    nY = int(np.ceil(len(ops1)/nX))
    dx = np.zeros((len(ops1),), 'int64')
    dy = np.zeros((len(ops1),),'int64')
    for j in range(len(ops1)):
        dx[j] = (j%nX) * Lx
        dy[j] = int(j/nX) * Ly
    meanImg = np.zeros((Ly*nX, Lx*nY))
    Vcorr = np.zeros((Ly*nX, Lx*nY))
    for k,ops in enumerate(ops1):
        fpath = ops['save_path']
        stat0 = np.load(os.path.join(fpath,'stat.npy'))
        meanImg[dy[k]:dy[k]+Ly, dx[k]:dx[k]+Lx] = ops['meanImg']
        Vcorr[dy[k] +ops['yrange'][0]:dy[k] +ops['yrange'][-1], dx[k] + ops['xrange'][0]:dx[k] + ops['xrange'][-1]] = ops['Vcorr']
        for j in range(len(stat0)):
            stat0[j]['xpix'] += dx[k]
            stat0[j]['ypix'] += dy[k]
            stat0[j]['med'][0] += dx[k]
            stat0[j]['med'][1] += dy[k]
        F0    = np.load(os.path.join(fpath,'F.npy'))
        Fneu0 = np.load(os.path.join(fpath,'Fneu.npy'))
        spks0 = np.load(os.path.join(fpath,'spks.npy'))
        if k==0:
            F, Fneu, spks,stat = F0, Fneu0, spks0,stat0
        else:
            F    = np.concatenate((F, F0))
            Fneu = np.concatenate((Fneu, Fneu0))
            spks = np.concatenate((spks, spks0))
            stat = np.concatenate((stat,stat0))
    ops['meanImg'] = meanImg
    ops['Vcorr'] = Vcorr
    ops['Ly'] = Ly * nY
    ops['Lx'] = Lx * nX
    ops['xrange'] = [0, ops['Lx']]
    ops['yrange'] = [0, ops['Ly']]
    fpath = os.path.join(ops['save_path0'], 'suite2p', 'combined')
    if not os.path.isdir(fpath):
        os.makedirs(fpath)
    ops['save_path'] = fpath
    np.save(os.path.join(fpath, 'F.npy'), F)
    np.save(os.path.join(fpath, 'Fneu.npy'), Fneu)
    np.save(os.path.join(fpath, 'spks.npy'), spks)
    np.save(os.path.join(fpath, 'ops.npy'), ops)
    np.save(os.path.join(fpath, 'stat.npy'), stat)
    iscell = np.ones((len(stat),2))
    np.save(os.path.join(fpath, 'iscell.npy'), iscell)
    return ops

def run_s2p(ops={},db={}):
    i0 = tic()

    ops = {**ops, **db}

    if 'save_path0' not in ops or len(ops['save_path0'])==0:
        ops['save_path0'] = ops['data_path'][0]

    # check if there are files already registered
    fpathops1 = os.path.join(ops['save_path0'], 'suite2p', 'ops1.npy')
    files_found_flag = True
    if os.path.isfile(fpathops1):
        ops1 = np.load(fpathops1)
        files_found_flag = True
        for i,op in enumerate(ops1):
            files_found_flag &= os.path.isfile(op['reg_file'])
            # use the new options
            ops1[i] = {**op, **ops}
            # except for registration results
            ops1[i]['xrange'] = op['xrange']
            ops1[i]['yrange'] = op['yrange']
    else:
        files_found_flag = False

    ######### REGISTRATION #########
    if not files_found_flag:
        # get default options
        ops0 = default_ops()
        # combine with user options
        ops = {**ops0, **ops}
        # copy tiff to a binary
        if len(ops['h5py']):
            ops1 = register.h5py_to_binary(ops)
            print('time %4.4f. Wrote h5py to binaries for %d planes'%(toc(i0), len(ops1)))
        else:
            ops1 = register.tiff_to_binary(ops)
            print('time %4.4f. Wrote tifs to binaries for %d planes'%(toc(i0), len(ops1)))
        # register tiff
        ops1 = register.register_binary(ops1)
        # save ops1
        np.save(fpathops1, ops1)
        print('time %4.4f. Registration complete'%toc(i0))
    else:
        print('found ops1 and pre-registered binaries')
        print(ops1[0]['reg_file'])
        print('overwriting ops1 with new ops')
        print('skipping registration...')

    ######### CELL DETECTION #########
    if len(ops1)>1 and ops['num_workers_roi']>=0:
        if ops['num_workers_roi']==0:
            ops['num_workers_roi'] = len(ops1)
        with Pool(ops['num_workers_roi']) as p:
            ops1 = p.map(get_cells, ops1)
    else:
        for k in range(len(ops1)):
            ops1[k] = get_cells(ops1[k])

    ######### SPIKE DECONVOLUTION #########
    for ops in ops1:
        fpath = ops['save_path']
        F = np.load(os.path.join(fpath,'F.npy'))
        Fneu = np.load(os.path.join(fpath,'Fneu.npy'))
        dF = F - ops['neucoeff']*Fneu
        spks = dcnv.oasis(dF, ops)
        print('time %4.4f. Detected spikes in %d ROIs'%(toc(i0), F.shape[0]))
        np.save(os.path.join(ops['save_path'],'spks.npy'), spks)

    # save final ops1 with all planes
    np.save(fpathops1, ops1)

    #### COMBINE PLANES or FIELDS OF VIEW ####
    if len(ops1)>1 and ops1[0]['combined']:
        combined(ops1)

    for ops in ops1:
        if ('delete_bin' in ops) and ops['delete_bin']:
            os.remove(ops['reg_file'])
            if ops['nchannels']>1:
                os.remove(ops['reg_file_chan2'])

    print('finished all tasks in total time %4.4f sec'%toc(i0))
    return ops1
