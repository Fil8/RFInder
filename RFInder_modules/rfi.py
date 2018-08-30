# Import modules
import sys, string, os
import numpy as np
import yaml
import json
import glob
import pyrap.tables as tables

import logging

from astropy.io import fits, ascii
from astropy import units as u
from astropy.table import Table, Column, MaskedColumn





__author__ = "Filippo Maccagni, Tom Oosterloo"
__copyright__ = "RadioLife"
__version__ = "1.0.0"
__email__ = "filippo.maccagni@gmail.com"
__status__ = "Development"

class rfi:

    def __init__(self):

       #set logger
        self.logger = logging.getLogger('RFInder')
        self.logger.info("\t Initializing RFInder\n")

    def load_from_ms(self,cfg_par):
        '''

        Loads important columns from MS file
        From MS: 
        Field_ID, Data, Flag, Antenna1, Antenna2,
        From MS/ANTENNA:
        Position,Name
        From MS/SPECTRAL_WINDOW
        Chan_width, Chan_freq

        '''

        self.logger.info("\t Loading file from MS\n")

        t=tables.table(self.msfile)

        self.fieldIDs=t.getcol('FIELD_ID')
        self.vis = t.getcol('DATA')
        self.flag = t.getcol('FLAG')
        self.ant1=t.getcol('ANTENNA1')
        self.ant2=t.getcol('ANTENNA2')
        
        t.close()

        #
        antennas = tables.table(self.msfile +'/ANTENNA')
        self.ant_pos = np.array(antennas.getcol('POSITION'))
        self.ant_wsrtnames = np.array(antennas.getcol('NAME'))
        self.ant_names = np.arange(0,self.ant_wsrtnames.shape[0],1)
        self.nant = len(self.ant_names)
        self.logger.info("\tTotal number of antennas\t:"+str(self.nant))
        self.logger.info("\tAntenna names\t"+str(self.ant_names))

        print "\tTotal number of antennas\t:"+str(self.nant)
        print "\tAntenna names\t"+str(self.ant_names)
        

        antennas.close()

        spw=tables.table(self.msfile+'/SPECTRAL_WINDOW')
        self.channelWidths=spw.getcol('CHAN_WIDTH')
        self.channelFreqs=spw.getcol('CHAN_FREQ')
        self.logger.info("\tBandwidth\t:"+str(self.channelWidths))
        self.logger.info("\tStart Frequency\t:"+str(self.channelFreqs[0][0]))
        self.logger.info("\tEnd Frequency\t:"+str(self.channelFreqs[-1][0]))

        print "\tBandwidth [kHz]\t:"+str(self.channelWidths[0][0]/1e3)
        print "\tStart Frequency [GHz]\t:"+str(self.channelFreqs[0][0]/1e9)
        print "\tEnd Frequency [GHz]\t:"+str(self.channelFreqs[-1][-1]/1e9)
        spw.close()


        return 

    def baselines_from_ms(self,cfg_par):
        '''

        Reads which baselines were used in the observations
        Stores them sorted by lenght in the array baselines_sort
        Creates the Matrix to analize visibilites on each baseline separately

        '''

        #sort baselines by length
        baselines = []
        for i in range(0,self.nant-1) :
            for j in range(i+1,self.nant) :
                # Exclude anticorrelations
                if self.aperfi_badant != None:
                    if self.ant_names[i]!=self.ant_names[j] and any(x != self.ant_names[i] for x in self.aperfi_badant) and any(x != self.ant_names[i] for x in self.aperfi_badant):
                        #distances are in units of meters
                        xdiff = (self.ant_pos[i,0]-self.ant_pos[j,0])*(self.ant_pos[i,0]-self.ant_pos[j,0])
                        ydiff = (self.ant_pos[i,1]-self.ant_pos[j,1])*(self.ant_pos[i,1]-self.ant_pos[j,1])
                        zdiff = (self.ant_pos[i,2]-self.ant_pos[j,2])*(self.ant_pos[i,2]-self.ant_pos[j,2])

                        dist = np.sqrt(xdiff+ydiff+zdiff)
                        baselines.append(([self.ant_names[i],self.ant_names[j]],dist))
                else: 
                    if self.ant_names[i]!=self.ant_names[j]:
                        #distances are in units of meters
                        xdiff = (self.ant_pos[i,0]-self.ant_pos[j,0])*(self.ant_pos[i,0]-self.ant_pos[j,0])
                        ydiff = (self.ant_pos[i,1]-self.ant_pos[j,1])*(self.ant_pos[i,1]-self.ant_pos[j,1])
                        zdiff = (self.ant_pos[i,2]-self.ant_pos[j,2])*(self.ant_pos[i,2]-self.ant_pos[j,2])

                        dist = np.sqrt(xdiff+ydiff+zdiff)
                        baselines.append(([self.ant_names[i],self.ant_names[j]],dist))


        self.baselines_sort = sorted(baselines, key=lambda baselines: baselines[1])  

        # Define matrix of indecese of baselines                                         
        self.blMatrix=np.zeros((self.nant,self.nant),dtype=int)
        for i in range(0,len(self.baselines_sort)) :

            ant1 = self.baselines_sort[i][0][0]
            ant2 = self.baselines_sort[i][0][1]
            self.blMatrix[ant1,ant2] = i
            self.blMatrix[ant2,ant1] = i

        print self.blMatrix

    def priors_flag(self,cfg_par):
        '''

        Flags YY,XY,YX polarizations
        Flags autocorrelations
        Flags bad antennas set by aperfi_badant = [ x, y, z ]
        Stores them sorted by lenght in the array baselines_sort

        '''

        self.datacube = np.zeros([len(self.baselines_sort),self.vis.shape[1],self.vis.shape[0]/(len(self.baselines_sort))])
        baseline_counter = np.zeros((self.nant,self.nant),dtype=int)

        #flag unused polarizations
        self.flag[:,:,1] = True #YY
        self.flag[:,:,2] = True #XY
        self.flag[:,:,3] = True #YX

        #flag autocorrelations and bad antennas
        for i in xrange(0,self.vis.shape[0]):

            if self.ant1[i] == self.ant2[i]:
                self.flag[i,:,0] = True
                
            elif self.aperfi_badant != None:
                if (any(x == self.ant1[i] for x in self.aperfi_badant) or any(x == self.ant2[i] for x in self.aperfi_badant)):
                    self.flag[i,:,0] = True

            else:
                a1 = self.ant1[i]
                a2 = self.ant2[i]
                indice=self.blMatrix[a1,a2]
                # Count how many visibilities per baseline
                counter=baseline_counter[a1,a2]
                # Put amplitude of visibility
                # In the right place in the new array
                self.datacube[indice,:,counter]=np.abs(self.vis[i,:,0])
                # Update the number of visibility in that baseline
                baseline_counter[a1,a2]+=1

        #self.datacube = np.transpose(self.datacube, (1, 0, 2)) 


    

    def find_rfi(self,cfg_par):
        '''

        For each baseline finds all signal above rms*aperfi_clip
        Creates a cube of visibilities sorted by baseline_lengh , frequency, time
        Stores them sorted by lenght in the array baselines_sort
        Creates the Matrix to analize visibilites on each baseline separately

        '''


        self.rms = np.zeros([self.datacube.shape[0],self.datacube.shape[1]])
        self.mean_array = np.zeros([self.datacube.shape[0],self.datacube.shape[1]])
        self.flag_lim_array= np.zeros([self.datacube.shape[0]])

        chan_min = np.argmin(np.abs(self.channelFreqs[0] - self.aperfi_rfifree_min))
        chan_max = np.argmin(np.abs(self.channelFreqs[0] - self.aperfi_rfifree_max))
        time_ax_len = int(self.datacube.shape[2])
        for i in xrange(0,self.datacube.shape[0]):
            tmp_rms = np.nanmedian(self.datacube[i, chan_min:chan_max, 0])
            med2 = abs(self.datacube[i, chan_min:chan_max, 0] - tmp_rms)
            madfm = np.ma.median(med2) / 0.6744888
            flag_lim = self.aperfi_rmsclip*madfm  
            self.flag_lim_array[i] = flag_lim    

            for j in xrange(0,self.datacube.shape[1]):
                tmpar = self.datacube[i,j,:]
                mean  = np.nanmean(tmpar)
                tmpar = tmpar-mean
                tmpar = abs(tmpar)
                self.mean_array[i,j] = mean
                #change masked values to very high number
                #inds = np.where(np.isnan(tmpar))
                tmpar[np.isnan(tmpar)]=np.inf
                tmpar.sort()
                index_rms = np.argmin(np.abs(tmpar - flag_lim))
                tmp_over = len(tmpar[index_rms:-1])+1
                if tmp_over == 1. :
                    tmp_over = 0.
                self.rms[i,j] = 100.*tmp_over/time_ax_len

        self.write_freq_base()

        return 0

    def write_freq_base(self,cfg_par) :
        '''
        
        Writes an image.fits of visibilities ordered by frequency, baseline.
        Baselines are ordered by their length.
        
        '''
        #reverse frequencies if going from high-to-low         
        
        #set fits file
        hdu = fits.PrimaryHDU(self.rms)
        hdulist = fits.HDUList([hdu])
        header = hdulist[0].header
        #write header keywords               
        header['CRPIX1'] = 1
        header['CDELT1'] = np.abs(self.channelWidths[0,0]/1e6)
        header['CRVAL1'] = self.channelFreqs[0,0]/1e6
        header['CTYPE1'] = ('Frequency')
        header['CUNIT1'] = ('MHz')
        header['CRPIX2'] = 1
        header['CRVAL2'] = 1
        header['CDELT2'] = 1
        header['CTYPE2'] =  ('Baseline')
        header['POLAR'] =  ('XX')
        header['BUNIT'] = ('% > '+str(5)+'*rms')
        header['BTYPE'] = ('intensity')
        #write file
        fits.writeto(self.rfi_freq_base,self.rms,header)
        hdulist.close()

        return 0




    def rfi_flag(self,cfg_par):
        '''
        Creates a new MS file where RFI has been flagged in the FLAG column
        '''

        #self.flag_lim_array = np.zeros([self.vis.shape[0]])
        for i in xrange(0,self.vis.shape[0]):
            
            if any(x == self.ant1[i] for x in self.aperfi_badant) or any(x == self.ant2[i] for x in self.aperfi_badant):
                continue
            else:
                indice=self.blMatrix[self.ant1[i],self.ant2[i]]
                flag_clip = self.flag_lim_array[indice]
            
            for j in xrange(0,self.vis.shape[1]):
                mean = self.mean_array[indice,i]
                if (np.abs(self.vis[i,j,0]) - mean ) > flag_clip:
                
                    self.flag[i,j,0] = True
        
        t=tables.table(self.msfile)
        tout = t.copy(self.rfifile)       # make deep copy
        tout.close()
        t.close()
        tout = tables.table(self.rfifile, readonly=False)
        #coldmi = tout.getdminfo('DATA')     # get dminfo of existing column
        #coldmi["NAME"] = 'CORRECTED_DATA'               # give it a unique name
        #tout.addcols(tables.maketabdesc(tables.makearrcoldesc("CORRECTED_DATA",0., ndim=2)),
        #           coldmi)
        #tout.putcol('CORRECTED_DATA',vis)
        tout.putcol('FLAG',self.flag)
        tout.close()

        return 0

