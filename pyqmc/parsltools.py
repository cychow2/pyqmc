# This must be done BEFORE importing numpy or anything else.
# Therefore it must be in your main script.
import os
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
import parsl
from parsl.app.app import python_app

import numpy as np
import time

@python_app
def vmcparsl(wf,lastrun,nsteps,accumulators,stepoffset=0):
    import os
    os.environ["MKL_NUM_THREADS"] = "1"
    os.environ["NUMEXPR_NUM_THREADS"] = "1"
    os.environ["OMP_NUM_THREADS"] = "1"
    
    from pyqmc.mc import vmc
    import copy
    import numpy as np
    
    df,coords=vmc(copy.copy(wf),np.asarray(lastrun[1]).copy(),
                 nsteps=nsteps,
                 accumulators=copy.copy(accumulators),
                 stepoffset=stepoffset)
    return df,coords.tolist()


        
def distvmc(wf,coords,accumulators=None,nsteps=100,npartitions=2,nsteps_per=None,sleeptime=5):
    """ 
    Args: 
    wf: a wave function object

    coords: nconf x nelec x 3 

    nsteps: how many steps to move each walker


    """
    if nsteps_per is None:
        nsteps_per=nsteps
    
    if accumulators is None:
        accumulators={}
            
    allruns=[]
    niterations=int(nsteps/nsteps_per)
    coord=np.split(coords,npartitions)
    for epoch in range(niterations):
        for p in range(npartitions):
            if epoch==0:
                allruns.append(vmcparsl(wf,([],coord[p]),nsteps_per,accumulators))
            else:
                allruns.append(vmcparsl(wf,allruns[-npartitions],
                               nsteps_per,
                               accumulators,
                               stepoffset=epoch*nsteps_per))
    import pandas as pd
    import time
    while True:
        print("Jobs done: {0}/{1}".format(np.sum([r.done() for r in allruns]),len(allruns)), flush=True)
        df=[]
        for r in allruns:
            if r.done():
                df.extend(r.result()[0])
        if np.all([r.done() for r in  allruns]):
            break
        time.sleep(sleeptime)

    coords=np.asarray(np.concatenate([x.result()[1] for x in allruns[-npartitions:]]))
    
    return df,coords

@python_app
def lmparsl(wf, configs, params, pgrad_acc):
    import os
    os.environ["MKL_NUM_THREADS"] = "1"
    os.environ["NUMEXPR_NUM_THREADS"] = "1"
    os.environ["OMP_NUM_THREADS"] = "1"

    from pyqmc.linemin import lm_sampler 
    import copy
    import numpy as np

    data = lm_sampler(copy.copy(wf), np.array(configs), np.array(params), copy.copy(pgrad_acc))
    for d in data:
        for k in d:
            d[k] = d[k].tolist() 
    return data

def dist_lm_sampler(wf, 
    configs, 
    params,
    pgrad_acc, 
    npartitions=2,
    sleeptime=5
    ):
    """
    Evaluates accumulator on the same set of configs for correlated sampling of different wave function parameters.  Parallelized with parsl.

    Args:
        wf: wave function object
        configs: (nconf, nelec, 3) array
        params: (nsteps, nparams) array 
            list of arrays of parameters (serialized) at each step
        pgrad_acc: PGradAccumulator 

    kwargs:
        npartitions: number of tasks for parallelization
            divides configs array into npartitions chunks
        sleeptime: time to wait between checking for results from parsl jobs

    Returns:
        data: list of dicts, one dict for each sample
            each dict contains arrays returned from pgrad_acc, weighted by psi**2/psi0**2 
    """
    import copy
    configspart = np.split(configs,npartitions)
    allruns = []
    for p in range(npartitions):
        allruns.append(lmparsl(wf, configspart[p], params, pgrad_acc))
    
    import time
    while True:
        print("Jobs done: {0}/{1}".format(np.sum([r.done() for r in allruns]),len(allruns)), flush=True)
        if np.all([r.done() for r in  allruns]):
            break
        time.sleep(sleeptime)

    stepsresults = zip(*[x.result() for x in allruns]) # length should be nsteps

    data = []
    df = {}
    for result in stepsresults:
        # result is a list of dicts, coming from the partitions
        df['dpH'] = np.concatenate([r['dpH'] for r in result], axis=0)
        df['dppsi'] = np.concatenate([r['dppsi'] for r in result], axis=0)
        df['dpidpj'] = np.concatenate([r['dpidpj'] for r in result], axis=0)
        df['total'] = np.concatenate([r['total'] for r in result], axis=0)
        data.append(df.copy())
    
    return data 

def line_minimization(*args,npartitions=2,**kwargs):
    import pyqmc
    if 'vmcoptions' in kwargs:
        kwargs['vmcoptions']['npartitions']=npartitions
    else:
        kwargs['vmcoptions']={'npartitions':npartitions}
    if 'lmoptions' in kwargs:
        kwargs['lmoptions']['npartitions']=npartitions
    else:
        kwargs['lmoptions']={'npartitions':npartitions}
    return pyqmc.line_minimization(*args,vmc=distvmc, lm=dist_lm_sampler, **kwargs)
    
        
def clean_pyscf_objects(mol,mf):
    mol.output=None
    mol.stdout=None
    mf.output=None
    mf.stdout=None
    mf.chkfle=None
    return mol,mf



    
                
                

            
