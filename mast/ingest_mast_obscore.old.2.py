#!/usr/bin/env python

"""
Create RDF/XML or N3 versions of the input file, which
is assumed to be in pipe-separated format and have no header line.

"""
#DATA="../mast_hut-rdf"
import sys 
import math
#import hashlib
import base64

from rdflib import URIRef, Literal, Graph

from namespaces import *
from psv import open_obscore, row2dict
from mast_utils import *

def mean(blist):
    alist=[float(item) for item in blist]
    return sum(alist)/float(len(alist))
    
def pdev(blist):
    try:
        alist=[float(item) for item in blist]
    except:
        return "",""
    m=mean(alist)
    s2=sum([(x-m) ** 2 for x in alist])
    return m, 100*math.sqrt(s2/float(len(alist)))

def addObsCoreRow(row):
    """Returns a Graph representing the given row. We do not add it to the
    main graph here in case there is invalid data for this row. Perhaps
    it would be better to have all validity checks first and then add
    direcctly to the graph, since it may be faster once the main graph
    starts getting large (unlikely).

    Errors may be thrown if the input is invalid (e.g. unable to coerce
    a cell into the correct type).
    """

    vals = row2dict(row)

    # We use this as a hash and assume it is a unique value
    # (could check this assumption as we process the files, but
    # it was true in the original dataset).
    #
    # Originally I had used the obs_id cell as a unique identifier for
    # both observation and dataset, but it turned out not to be unique
    # enough. It may be that this is down to the modelling, where we try
    # to associate as much information as possible with the observation,
    # rather than the data product. If the observation were very light-weight
    # then we could keep this as an identifier for the observation, but
    # would still need unique identifiers for the data values.
    #
    # We reverse the access URL before hashing to try and reduce collisions.
    # This is a bit silly and needs replacing; for instance
    # we do not need this many characters and the current "hash" scheme isn't
    # very unique.
    #
    access_url = vals['access_url']
    if access_url.strip() == '':
        raise ValueError("Empty access_url for row")
    
    obs_id = vals['obs_id']
    if obs_id == '':
        raise ValueError("No obs_id value in this row!")
    
    # We use a scheme based on the path
    #    
    #    xxx/data/MAST/obsid/<obs_id>/<hash>
    #    xxx/observation/MAST/obsid/<obs_id>/<hash>
    #
    # where <hash> is a "hash" of the access_url value.
    # This is intentended to
    #   - reduce file sizes (e.g. use of slash rather than hash URI)
    #   - be more REST-ful in that we can define properties for parents
    #     of these URIs to manage and merge data
    #   - allow somewhat easier updates in case of changes - e.g to
    #     the data location because a server changes so access_url
    #     changes but nothing else does
    #
    uri_hash = base64.urlsafe_b64encode(access_url[::-1])
    daturi = mkURI("/obsv/data/MAST/obsid/{0}/".format(obs_id), uri_hash)
    #obsuri = mkURI("/obsv/observation/MAST/obsid/{0}/".format(obs_id), uri_hash)
    obsuri = mkURI("/obsv/observation/MAST/obsid/{0}/".format(obs_id))
    graph = Graph()

    # Can we assume this is a SimpleObservation or could it be a
    # ComplexObservation? Not convinced we can tell, so
    # use the parent Observation class for now.
    #
    #gadd(graph, obsuri, a, adsobsv.SimpleObservation)
    gadd(graph, obsuri, a, adsobsv.Observation)

    # For now assuming we have a Datum rather than a DataSet;
    # we could use the parent SingularDataProdict but try
    # this.
    #
    gadd(graph, daturi, a, adsobsv.Datum)
    #gadd(graph, daturi, a, adsobsv.SingularDataProduct)

    #gadd(graph, obsuri, adsobsv.hasDatum, daturi)
    gadd(graph, obsuri, adsobsv.hasDataProduct, daturi)

    #gadd(graph, daturi, adsobsv.forSimpleObservation, obsuri)
    gadd(graph, daturi, adsobsv.forObservation, obsuri)

    # Qus: should we use obs_id for both here?
    gadd(graph, obsuri, adsobsv.observationId, Literal(obs_id))
    gadd(graph, daturi, adsobsv.dataProductId, Literal(obs_id))

    ### Observational properties
    #
    emmin = vals['em_min']
    emmax = vals['em_max']

    addVals(graph, obsuri,
            [
                adsbase.atTime, vals['date_obs'], asDateTime(),
                # not convinced that observerTime is worth it, as a xsd:duration
                adsobsv.observedTime, vals['t_exptime'], asDuration,
                adsobsv.tExptime, vals['t_exptime'], asDouble,

                adsobsv.resolution, vals['s_resolution'], asDouble,
                adsobsv.tResolution, vals['t_resolution'], asDouble,

                adsobsv.wavelengthStart, emmin, asDouble,
                adsobsv.wavelengthEnd, emmax, asDouble,

                adsbase.title, vals['title'], Literal,
                
                adsobsv.fov, vals['s_fov'], asDouble,

            ])

    # For now we create a URI for each target_name and make
    # it an AstronomicalSourceName. We know that this is not
    # always "sensible", in that some names are not sources as
    # such but calibration values (e.g. '20% UV FLOOD' or
    # 'NULL SAFETY RD') or some scheme of the observer
    # which may be positional or something else (e.g. '+014381').
    #
    tname = vals['target_name'].strip()
    if tname != '':
        tnameuri = mkURI("/obsv/target/MAST/", tname)

        gadd(graph, obsuri, adsbase.target, tnameuri)
        addVals(graph, tnameuri,
                [
                    a, adsobsv.AstronomicalSourceName, None,
                    adsbase.name, tname, Literal,
                    ])

    # We do not use the em_domain field since the values found in
    # the MAST table do not appear to match the ObsCore/VODataService
    # enumerations. Instead we create values based on the em_min/max
    # fields. These could be inferred but worth being explicit here.
    #
    for domain in getEMDomains(float(emmin), float(emmax)):
        addVal(graph, obsuri, adsobsv.wavelengthDomain, domain)

    sra = vals['s_ra']
    sdec = vals['s_dec']
    if sra != '' and sdec != '':
        gdbnadd(graph, obsuri, adsobsv.associatedPosition,
                [
                    a, adsobsv.Pointing,
                    adsobsv.ra, asDouble(sra),
                    adsobsv.dec, asDouble(sdec),
                ])

    sregion = vals['s_region']
    if sregion != '':
        predList = [
                a, adsobsv.FootPrint,
                adsobsv.s_region, Literal(sregion),
            ]
            
        gdbnadd(graph, obsuri, adsobsv.associatedFootprint, predList)

    # TODO:
    #   - work out what prefix to use; for now guessing uri_conf is okay,
    #     since that's what the Chandra pipeline uses, but would uri_obsv be
    #     better? Alternatively, move to a scheme more like the other URIs
    #     we create here
    #
    tname = vals['telescope_name']
    iname = vals['instrument']
    oname="MAST"
    gadd(graph, obsuri, adsobsv.atObservatory,
             addFragment(uri_infra, 'observatory/' + oname))
    if tname != '':
        gadd(graph, obsuri, adsobsv.atTelescope,
             addFragment(uri_infra, 'telescope/MAST_' + tname))

    if iname != '':
        gadd(graph, obsuri, adsbase.usingInstrument,
             addFragment(uri_infra, 'instrument/MAST_' + iname))

    ### Data set properties
    #
    gadd(graph, daturi, adsobsv.dataURL, URIRef(access_url))
    #BUG: fix this to use a mapper
    dprodtype="image"#DEFAULT
    if vals['dataproduct_type'].find("Spectrum.") != -1:
        dprodtype="spectra"
    elif vals['dataproduct_type'].find("Image.") != -1:
        dprodtype="image"
    addVals(graph, daturi,
            [
                pav.createdOn, vals['creation_date'], asDateTime(),
                adsobsv.calibLevel, vals['calib_level'], asInt,

                adsbase.dataType, dprodtype, Literal, # could be a URI; how standardised are the values?
                adsobsv.dataFormat, vals['access_format'], Literal, # could be a URI; how standardised are the values?
            ])

    # Adding a link to the IVOA identifier for completeness.
    # Since this is the dataset identifier, we link it to the
    # dataset rather than the observation.
    #
    gadd(graph, daturi, adsbase.hasIVOAIdentifier,
         URIRef(vals['obs_publisher_did']))
        
    # The scheme for creator and collection URI is
    #
    #    xxx/creator/MAST/<obs_creator_name>
    #    xxx/collection/MAST/<obs_collection>
    #
    # although <obs_collection> can be an IVOA identifier, which means
    # we use that instead; this breaks linked-data approach, so perhaps
    # need a predicate to say "this represents this IVOA id" (could
    # use owl:sameAs but not convinced we want this).
    #
    #   - should I replace / by some other character since it could
    #     confuse some parsers? Replace space with ?
    #
    #   - upper case all characters under the assumption that case
    #     is not important and that there may be differences in case
    #
    cname = vals['obs_creator_name']
    if cname != '':
        # Is this correct; ie is the obs_creator_name really
        # the same as observationMadeBy?
        #
        #cnameuri = mkURI("/obsv/creator/MAST/", cname)
        cnameuri=addFragment(uri_conf, 'project/MAST_' + cname)
        gadd(graph, obsuri, adsobsv.observationMadeBy, cnameuri)
        #gdadd(graph, cnameuri, [
        #    a, agent.PersonName,
        #    agent.fullName, Literal(cname)
        #    ])

    ocoll = vals['obs_collection']
    if ocoll != '':
        if is_ivoa_uri(ocoll):
            colluri = URIRef(ocoll)
        else:
            colluri = mkURI("/obsv/collection/MAST/", ocoll)

        addVal(graph, daturi, adsobsv.fromDataCollection, colluri)
        gdadd(graph, colluri, [
            a, adsobsv.DataCollection,
            adsbase.name, Literal(ocoll)
            ])

    return graph

def addObsCoreObs(dkey, valstuplearray, obsdatahash):

    print "=============================================================="
    if dkey == '':
        raise ValueError("No obs_id value in this row!")
    print "FOR DKEY OBSID:",dkey, len(valstuplearray)
    valsarray=[tup[0] for tup in valstuplearray]
    anbools=[tup[4] for tup in valstuplearray]
    print [vals['access_url'].split('/')[-1] for vals in valsarray]
    # We use a scheme based on the path
    #    
    #    xxx/data/MAST/obsid/<obs_id>/<hash>
    #    xxx/observation/MAST/obsid/<obs_id>/<hash>
    #
    # where <hash> is a "hash" of the access_url value.
    # This is intentended to
    #   - reduce file sizes (e.g. use of slash rather than hash URI)
    #   - be more REST-ful in that we can define properties for parents
    #     of these URIs to manage and merge data
    #   - allow somewhat easier updates in case of changes - e.g to
    #     the data location because a server changes so access_url
    #     changes but nothing else does
    #

    #obsuri = mkURI("/obsv/observation/MAST/obsid/{0}/".format(obs_id), uri_hash)
    obsuri = mkURI("/obsv/observation/MAST/obsid/{0}/".format(dkey))
    graph = Graph()

    # Can we assume this is a SimpleObservation or could it be a
    # ComplexObservation? Not convinced we can tell, so
    # use the parent Observation class for now.
    #
    #gadd(graph, obsuri, a, adsobsv.SimpleObservation)
    gadd(graph, obsuri, a, adsobsv.Observation)
    obsdatahash[obsuri]=[]
    for vals in valsarray:
        # For now assuming we have a Datum rather than a DataSet;
        # we could use the parent SingularDataProdict but try
        # this.
        #
        #print "VALS",vals
        obs_id = vals['obs_id']
        if obs_id == '':
            raise ValueError("No obs_id value in this row!")
        gadd(graph, obsuri, adsobsv.observationId, Literal(obs_id))
        #gadd(graph, daturi, a, adsobsv.SingularDataProduct)
        access_url = vals['access_url']
        #print "access url", access_url
        if access_url.strip() == '':
            raise ValueError("Empty access_url for row")
        uri_hash = base64.urlsafe_b64encode(access_url[::-1])
        daturi = mkURI("/obsv/data/MAST/obsid/{0}/".format(dkey), uri_hash)    
        #gadd(graph, obsuri, adsobsv.hasDatum, daturi)
        gadd(graph, daturi, a, adsobsv.Datum)
        gadd(graph, obsuri, adsobsv.hasDataProduct, daturi)
        obsdatahash[obsuri].append(daturi)
        #gadd(graph, daturi, adsobsv.forSimpleObservation, obsuri)
        gadd(graph, daturi, adsobsv.forObservation, obsuri)

        # Qus: should we use obs_id for both here?
    
        gadd(graph, daturi, adsobsv.dataProductId, Literal(obs_id))

        #
        gadd(graph, daturi, adsobsv.dataURL, URIRef(access_url))
        #BUG: fix this to use a mapper
        dprodtype="image"#DEFAULT
        if vals['dataproduct_type'].find("Spectrum.") != -1:
            dprodtype="spectra"
        elif vals['dataproduct_type'].find("Image.") != -1:
            dprodtype="image"
        addVals(graph, daturi,
                [
                    pav.createdOn, vals['creation_date'], asDateTime(),
                    adsobsv.calibLevel, vals['calib_level'], asInt,

                    adsbase.dataType, dprodtype, Literal, # could be a URI; how standardised are the values?
                    adsobsv.dataFormat, vals['access_format'], Literal, # could be a URI; how standardised are the values?
                ])

        # Adding a link to the IVOA identifier for completeness.
        # Since this is the dataset identifier, we link it to the
        # dataset rather than the observation.
        #
        gadd(graph, daturi, adsbase.hasIVOAIdentifier,
             URIRef(vals['obs_publisher_did']))
            
        # The scheme for creator and collection URI is
        #
        #    xxx/creator/MAST/<obs_creator_name>
        #    xxx/collection/MAST/<obs_collection>
        #
        # although <obs_collection> can be an IVOA identifier, which means
        # we use that instead; this breaks linked-data approach, so perhaps
        # need a predicate to say "this represents this IVOA id" (could
        # use owl:sameAs but not convinced we want this).
        #
        #   - should I replace / by some other character since it could
        #     confuse some parsers? Replace space with ?
        #
        #   - upper case all characters under the assumption that case
        #     is not important and that there may be differences in case
        #
        cname = vals['obs_creator_name']
        if cname != '':
            # Is this correct; ie is the obs_creator_name really
            # the same as observationMadeBy?
            #
            #cnameuri = mkURI("/obsv/creator/MAST/", cname)
            cnameuri=addFragment(uri_conf, 'project/MAST_' + cname)
            gadd(graph, obsuri, adsobsv.observationMadeBy, cnameuri)
            #gdadd(graph, cnameuri, [
            #    a, agent.PersonName,
            #    agent.fullName, Literal(cname)
            #    ])

        ocoll = vals['obs_collection']
        if ocoll != '':
            if is_ivoa_uri(ocoll):
                colluri = URIRef(ocoll)
            else:
                colluri = mkURI("/obsv/collection/MAST/", ocoll)

            addVal(graph, daturi, adsobsv.fromDataCollection, colluri)
            gdadd(graph, colluri, [
                a, adsobsv.DataCollection,
                adsbase.name, Literal(ocoll)
                ])
                
        
    #NACK TO OBSURI            
    emminray = [vals['em_min'] for vals in valsarray]
    print 'emin', pdev(emminray), emminray
    emmin=pdev(emminray)[0]
    emmaxray = [vals['em_min'] for vals in valsarray]
    print 'emax', pdev(emmaxray), emmaxray
    emmax=pdev(emmaxray)[0]
    atray=[valts[0]['date_obs'] for valts in valstuplearray if valts[4]==1 or len(valstuplearray)==1]
    print "atTime", atray
    #SINCE the imscors are now supposedly buried unless by themselves, the mac should favor a over n or d
    exptray=[float(valts[0]['t_exptime']) for valts in valstuplearray if valts[4]==1 or len(valstuplearray)==1]
    print 'exptime', max(exptray), exptray
    tresray=[float(valts[0]['t_resolution']) for valts in valstuplearray if valts[4]==1 or len(valstuplearray)==1]
    print 'tres', max(tresray), tresray
    print 'access',[vals['access_url'].split('/')[-1] for vals in valsarray]
    sresray=[vals['s_resolution'] for vals in valsarray]
    print 'sres', pdev(sresray)
    
    sfovray=[vals['s_fov'] for vals in valsarray]
    print 's_fov', pdev(sfovray)
    titleray=[vals['title'] for vals in valsarray]
    print "Title", titleray
    addVals(graph, obsuri,
            [
                adsbase.atTime, atray[0], asDateTime(),
                # not convinced that observerTime is worth it, as a xsd:duration
                adsobsv.observedTime, pdev(exptray)[0], asDuration,
                adsobsv.tExptime, pdev(exptray)[0], asDouble,

                adsobsv.resolution, pdev(sresray)[0], asDouble,
                adsobsv.tResolution, pdev(tresray)[0], asDouble,

                adsobsv.wavelengthStart, emmin, asDouble,
                adsobsv.wavelengthEnd, emmax, asDouble,

                adsbase.title, titleray[0], Literal,
                
                adsobsv.fov, pdev(sfovray)[0], asDouble,

            ])

    # For now we create a URI for each target_name and make
    # it an AstronomicalSourceName. We know that this is not
    # always "sensible", in that some names are not sources as
    # such but calibration values (e.g. '20% UV FLOOD' or
    # 'NULL SAFETY RD') or some scheme of the observer
    # which may be positional or something else (e.g. '+014381').
    #
    tnameray = [vals['target_name'].strip() for vals in valsarray]
    print "TargetName",tnameray
    tname=tnameray[0]
    if tname != '':
        tnameuri = mkURI("/obsv/target/MAST/", tname)

        gadd(graph, obsuri, adsbase.target, tnameuri)
        addVals(graph, tnameuri,
                [
                    a, adsobsv.AstronomicalSourceName, None,
                    adsbase.name, tname, Literal,
                    ])

    # We do not use the em_domain field since the values found in
    # the MAST table do not appear to match the ObsCore/VODataService
    # enumerations. Instead we create values based on the em_min/max
    # fields. These could be inferred but worth being explicit here.
    #
    for domain in getEMDomains(float(emmin), float(emmax)):
        addVal(graph, obsuri, adsobsv.wavelengthDomain, domain)

    sraray = [vals['s_ra'] for vals in valsarray]
    sdecray = [vals['s_dec'] for vals in valsarray]

    if sraray[0] != '' and sdecray[0] != '':

        print "ra", pdev(sraray)
        print "dec", pdev(sdecray)
        gdbnadd(graph, obsuri, adsobsv.associatedPosition,
                [
                    a, adsobsv.Pointing,
                    adsobsv.ra, asDouble(pdev(sraray)[0]),
                    adsobsv.dec, asDouble(pdev(sdecray)[0]),
                ])

    sregionray = [vals['s_region'] for vals in valsarray]
    print "footprints", sregionray
    if sregionray[0] != '':
        predList = [
                a, adsobsv.FootPrint,
                adsobsv.s_region, Literal(sregionray[0]),
            ]
            
        gdbnadd(graph, obsuri, adsobsv.associatedFootprint, predList)

    # TODO:
    #   - work out what prefix to use; for now guessing uri_conf is okay,
    #     since that's what the Chandra pipeline uses, but would uri_obsv be
    #     better? Alternatively, move to a scheme more like the other URIs
    #     we create here
    #
    tnameray = [vals['telescope_name'] for vals in valsarray]
    print "telescope", tnameray
    inameray = [vals['instrument'] for vals in valsarray]
    print "instrument", inameray
    oname="MAST"
    gadd(graph, obsuri, adsobsv.atObservatory,
             addFragment(uri_infra, 'observatory/' + oname))
    if tname != '':
        gadd(graph, obsuri, adsobsv.atTelescope,
             addFragment(uri_infra, 'telescope/MAST_' + tnameray[0]))
    #In theory we have multiple instruments, so
    #should we not associate with dauri too?
    for iname in inameray:
        if iname != '':
            gadd(graph, obsuri, adsbase.usingInstrument,
                addFragment(uri_infra, 'instrument/MAST_' + iname))



    return graph

def getObsCoreFile(odhfname, fname, ohead, nsplit=10000, format="n3"):
    """Convert the given obscore file from MAST (in psv format) into
    RDF.

    Rows that can not be converted are ignored (an error message is
    displayed on STDERR in this case).

    Since the input file is large we now split apart the output every
    nsplit rows. The output is written to
    
        ohead.<i>.<format>

    where i is a counter, starting at 1
    """
    obsdatahash={}
    (rdr, fh) = open_obscore(fname)

    rnum = 0
    rpass = 0

    idx = 1
    graph = makeGraph()
    globalrowdict={}
    h_at={}
    for row in rdr:
        vals=row2dict(row)
        obs_id = vals['obs_id']
        at_time="_".join(vals['date_obs'].split())
        if obs_id == '':
            raise ValueError("No obs_id value in this row!")
        access_url = vals['access_url']
        access_name=access_url.split('/')[-1].split('_ph_')[0]
        if access_name.find('_sum') !=-1:
            access_name=access_name.split('_sum')[0]
        anbool=1
        if access_name.find('_imcscor')!=-1:
            access_name=access_name.split('_imcscor')[0]
            anbool=0
        #print "access url", access_url
        if access_url.strip() == '':
            raise ValueError("Empty access_url for row")
        dayfind=access_url.find(obs_id+"_d")
        nightfind=access_url.find(obs_id+"_n")
        afind=access_url.find(obs_id+"_a")
        if dayfind!=-1:
            d2key=obs_id+"_d"
            #dkey=obs_id#lets not to day separately
        elif afind!=-1:
            d2key=obs_id+"_a"
        elif nightfind!=-1:
            d2key=obs_id+"_a"
        else:
            d2key=obs_id
            
        #dkey=obs_id+"--"+access_name
        dkey=obs_id
        if not globalrowdict.has_key(dkey):
            globalrowdict[dkey]=[]
        globalrowdict[dkey].append((vals, at_time, access_name, d2key, anbool))
    
    #print "LLLLL"    
    for dkey in globalrowdict.keys():
        print "grd", dkey, len(globalrowdict[dkey])
        dalen=len(globalrowdict[dkey])
        h_an={}
        for ele in globalrowdict[dkey]:
            vals, at_time, access_name, d2key, anbool=ele
            print "time",at_time, dkey, access_name, anbool
            if not h_an.has_key(access_name):
                h_an[access_name]=[]
            if anbool==1 or dalen==1:
                h_an[access_name].append((ele, at_time))
            else:
                h_an[access_name].append((ele, None))
        #print "han", h_an
        h_an2={}        
        for item in h_an.keys():
            #Sprint "hanitem", h_an[item]
            thetimelist=[e[1] for e in h_an[item] if e[1]!=None]
            if len(thetimelist)>=1:
                thetime=thetimelist[0]
            else:
                #This happens like in pupaeast when there is only imscor
                print "OOOOOOOOOOOOOOOPS", len(thetimelist)
            h_an2[item]=[(e[0],thetime) for e in h_an[item]]
        print "deekee",dkey
        for k in h_an2.keys():
            for item in h_an2[k]:
                #print "<<<",item[0][0],">>>"
                if not h_at.has_key(dkey+"="+item[1]):
                    h_at[dkey+"="+item[1]]=[]
                h_at[dkey+"="+item[1]].append(item[0])
            
            
                    
            
        
        
    for oid in h_at.keys():
        print "OID",oid
        #print "<<<",h_at[oid],">>>"
        graph=addObsCoreObs(oid,h_at[oid], obsdatahash)
        writeGraph(graph,
                       "{0}.{1}.{2}".format(ohead, oid, format),
                       format=format)

            
    fh.close()
    fd=open(odhfname,"w")
    fd.write(str(obsdatahash))
    fd.close()


if __name__=="__main__":
    
    nargs = len(sys.argv)
    if nargs in [2,3,4] :
        import os.path
        fname=sys.argv[1]
        if nargs < 4:
            fmt = "rdf"
        else:
            fmt = sys.argv[3]

        validateFormat(fmt)
        
        bname=os.path.basename(fname)
        if nargs >=3:
            execfile(sys.argv[2])
        else:
            execfile("./mast/default.conf")
        ohead = DATA+"/" + bname
        odhfname=DATA+"/obsdatahash.map"
        getObsCoreFile(odhfname, fname, ohead, format=fmt, nsplit=1000)

    else:
        sys.stderr.write("Usage: {0} <filename> [conffile] [rdf|n3]\n".format(sys.argv[0]))
        sys.exit(-1)


